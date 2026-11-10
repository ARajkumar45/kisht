"""Policy guard: the brakes. The model plans and decides; every tool call passes through here
before it touches the ledger, and every decision (allowed or refused) is audited.

Rules (all limits come from the lender's YAML):
  R1 contact allowed: inside the contact window (lender's local time), not opted out,
     not on DND for voice, under the daily and weekly attempt caps.
  R2 identity first: no account detail and no account action before verify_identity succeeds;
     3 failed attempts lock the conversation.
  R3 promise limits: date between today and (due date + max days, or today + max days if
     already overdue); amount between the lender's minimum share and what is owed; at most
     `max_open_promises` open; saved only after the borrower's own clear yes to the read-back.
  R4 payment links only for an amount inside the same limits; idempotent per conversation.
  R5 waiver / settlement / restructure / dispute / hardship: no tool can do them; the agent can
     only escalate them to a human.
  R6 nothing the agent says may contain a banned phrase (threats, shaming).
Tools never take a loan or borrower id: they act only on the account bound to the
conversation, so a prompt injection cannot reach another borrower's data.
"""
from __future__ import annotations

import functools
import math
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from kisht.audit import AuditLog
from kisht.ledger import PromiseLimit, SqliteLedger
from kisht.lender import Lender
from kisht.ports import CallState

MAX_ID_ATTEMPTS = 3
FOLLOWUP_MAX_DAYS = 14


class GuardRefused(Exception):
    """A rule said no. `code` names the rule; `message` tells the model what to do instead."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _audited(action: str):
    def wrap(fn):
        @functools.wraps(fn)
        def inner(self: PolicyGuard, call_id: str, *args, **kwargs):
            try:
                result = fn(self, call_id, *args, **kwargs)
            except GuardRefused as e:
                self.audit.record(call_id=call_id, tenant_id=self.lender.id, action=action,
                                  args=kwargs, outcome="denied", detail=f"{e.code}: {e.message}")
                raise
            self.audit.record(call_id=call_id, tenant_id=self.lender.id, action=action,
                              args=kwargs, outcome="ok")
            return result
        return inner
    return wrap


class PolicyGuard:
    def __init__(self, lender: Lender, ledger: SqliteLedger, calls: CallState, audit: AuditLog,
                 now: Callable[[], datetime] | None = None):
        self.lender = lender
        self.ledger = ledger
        self.calls = calls
        self.audit = audit
        self.tz = ZoneInfo(lender.timezone)
        self._now = now or (lambda: datetime.now(self.tz))

    def now(self) -> datetime:
        return self._now().astimezone(self.tz)

    def today(self) -> date:
        return self.now().date()

    # ---------- R1: may we contact this borrower now? ----------

    def check_contact(self, borrower_id: str, channel: str) -> None:
        b = self.ledger.borrower(borrower_id)
        if b is None:
            raise GuardRefused("unknown_borrower", f"no borrower {borrower_id}")
        now = self.now()
        if channel not in self.lender.contact.channels:
            raise GuardRefused("channel_not_allowed", f"{channel} is not enabled for this lender")
        if not self.lender.contact.window.contains(now.time()):
            w = self.lender.contact.window
            raise GuardRefused("outside_contact_window",
                               f"contact only between {w.start:%H:%M} and {w.end:%H:%M}")
        if b["opted_out"]:
            raise GuardRefused("opted_out", "the borrower asked not to be contacted")
        if b["dnd"] and channel == "voice":
            raise GuardRefused("dnd", "number is on DND: no calls, chat only")
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = now - timedelta(days=7)
        recent = self.ledger.contacts_since(borrower_id, week_ago.isoformat())
        today_n = sum(1 for c in recent
                      if datetime.fromisoformat(c["started_utc"]) >= start_of_day)
        if today_n >= self.lender.contact.max_attempts_per_day:
            raise GuardRefused("daily_attempt_cap", "already contacted the maximum times today")
        if len(recent) >= self.lender.contact.max_attempts_per_week:
            raise GuardRefused("weekly_attempt_cap", "already contacted the maximum times this week")

    @_audited("start_contact")
    def start_contact(self, call_id: str, *, borrower_id: str, loan_id: str, channel: str) -> str:
        """Bind the conversation to one borrower and loan (after R1) and log the attempt."""
        self.check_contact(borrower_id, channel)
        if self.ledger.loan(loan_id) is None or self.ledger.loan(loan_id)["borrower_id"] != borrower_id:
            raise GuardRefused("loan_mismatch", "loan does not belong to this borrower")
        contact_id = self.ledger.log_contact(lender_id=self.lender.id, borrower_id=borrower_id,
                                             loan_id=loan_id, channel=channel, call_id=call_id,
                                             started_utc=self.now().isoformat())
        self.calls.set_state(call_id, borrower_id=borrower_id, loan_id=loan_id, channel=channel,
                             contact_id=contact_id, identity_verified=False, id_attempts=0)
        return contact_id

    # ---------- R2: identity ----------

    def _bound(self, call_id: str) -> tuple[str, str]:
        borrower_id = self.calls.get(call_id, "borrower_id")
        loan_id = self.calls.get(call_id, "loan_id")
        if not borrower_id or not loan_id:
            raise GuardRefused("no_account", "this conversation is not bound to an account")
        return borrower_id, loan_id

    def _require_identity(self, call_id: str) -> tuple[str, str]:
        borrower_id, loan_id = self._bound(call_id)
        if not self.calls.get(call_id, "identity_verified", False):
            raise GuardRefused("identity_not_verified",
                               "Verify identity first with verify_identity (date of birth or "
                               "PIN code). Do not share any account detail before that.")
        return borrower_id, loan_id

    @_audited("verify_identity")
    def verify_identity(self, call_id: str, *, date_of_birth: str | None = None,
                        pincode: str | None = None) -> dict[str, Any]:
        borrower_id, _ = self._bound(call_id)
        attempts = int(self.calls.get(call_id, "id_attempts", 0))
        if attempts >= MAX_ID_ATTEMPTS:
            raise GuardRefused("identity_locked",
                               "Too many failed checks. Do not share anything; offer to have the "
                               "lender's desk call back, or escalate_to_human with reason "
                               "wrong_person.")
        if not date_of_birth and not pincode:
            raise GuardRefused("missing_fact", "Ask for the date of birth or the PIN code.")
        b = self.ledger.borrower(borrower_id)
        ok = False
        if date_of_birth:
            ok = _parse_date(date_of_birth) == date.fromisoformat(b["dob"])
        if not ok and pincode:
            ok = re.sub(r"\D", "", pincode) == b["pincode"]
        if not ok:
            self.calls.incr(call_id, "id_attempts")
            left = MAX_ID_ATTEMPTS - attempts - 1
            raise GuardRefused("identity_mismatch",
                               f"That does not match. {left} attempt(s) left. Ask again politely; "
                               "never reveal the correct value.")
        self.calls.set_state(call_id, identity_verified=True)
        return {"verified": True, "name": b["name"]}

    # ---------- account reads ----------

    @_audited("get_dues")
    def get_dues(self, call_id: str) -> dict[str, Any]:
        _, loan_id = self._require_identity(call_id)
        loan = self.ledger.loan(loan_id)
        dues = self.ledger.dues(loan_id, self.today())
        lo, hi = self._amount_limits(loan_id)
        return {**dues.as_dict(), "product": loan["product"], "emi": loan["emi"],
                "open_promises": [{"amount": p["amount"], "date": p["promised_date"]}
                                  for p in self.ledger.open_promises(loan_id)],
                "allowed_promise": {"min_amount": lo, "max_amount": hi,
                                    "latest_date": self._latest_promise_date(loan_id).isoformat()}}

    # ---------- R3: promise to pay (two steps) ----------

    def _amount_limits(self, loan_id: str) -> tuple[int, int]:
        d = self.ledger.dues(loan_id, self.today())
        due_now = d.overdue_amount if d.overdue_amount else d.next_due_amount
        owed = d.overdue_amount + d.next_due_amount
        return math.ceil(due_now * self.lender.promises.min_part_payment_pct / 100), owed

    def _latest_promise_date(self, loan_id: str) -> date:
        d = self.ledger.dues(loan_id, self.today())
        base = self.today() if d.overdue_amount else (d.next_due_date or self.today())
        return base + timedelta(days=self.lender.promises.max_days_after_due)

    def _check_amount(self, loan_id: str, amount: int) -> None:
        lo, hi = self._amount_limits(loan_id)
        if hi <= 0:
            raise GuardRefused("nothing_due", "Nothing is due on this loan right now.")
        if not lo <= amount <= hi:
            raise GuardRefused("amount_out_of_policy",
                               f"Amount must be between Rs {lo} and Rs {hi}. Anything lower is a "
                               "hardship case: escalate_to_human with reason hardship.")

    @_audited("propose_promise")
    def propose_promise(self, call_id: str, *, amount: int, pay_date: str) -> dict[str, Any]:
        _, loan_id = self._require_identity(call_id)
        when = _parse_date(pay_date)
        if when is None:
            raise GuardRefused("bad_date", "Use the date format YYYY-MM-DD.")
        if when < self.today():
            raise GuardRefused("date_in_past", "The date is in the past.")
        latest = self._latest_promise_date(loan_id)
        if when > latest:
            raise GuardRefused("date_out_of_policy",
                               f"The latest date this lender allows is {latest:%d %B}. Later "
                               "than that is a hardship case: escalate_to_human.")
        self._check_amount(loan_id, amount)
        if len(self.ledger.open_promises(loan_id)) >= self.lender.promises.max_open_promises:
            raise GuardRefused("promise_exists", "There is already an open promise on this loan.")
        pending = {"amount": amount, "pay_date": when.isoformat(),
                   "read_back": f"Rs {amount} on {when:%A %d %B}"}
        self.calls.set_state(call_id, pending_promise=pending)
        self.calls.clear(call_id, "borrower_confirmed")       # a new proposal needs a new yes
        return pending

    def mark_borrower_yes(self, call_id: str) -> None:
        """Called by the session (code), never by the model, when the borrower's own words are a
        clear yes to the read-back."""
        self.calls.set_state(call_id, borrower_confirmed=True)
        self.audit.record(call_id=call_id, tenant_id=self.lender.id, action="borrower_yes",
                          args={}, outcome="ok")

    @_audited("confirm_promise")
    def confirm_promise(self, call_id: str) -> dict[str, Any]:
        _, loan_id = self._require_identity(call_id)
        pending = self.calls.get(call_id, "pending_promise")
        if not pending:
            raise GuardRefused("no_pending_promise", "No promise is waiting for confirmation.")
        if not self.calls.get(call_id, "borrower_confirmed", False):
            raise GuardRefused("borrower_not_confirmed", "The borrower has not said yes yet.")
        try:
            pid = self.ledger.add_promise(loan_id=loan_id, amount=pending["amount"],
                                          promised_date=date.fromisoformat(pending["pay_date"]),
                                          max_open=self.lender.promises.max_open_promises,
                                          call_id=call_id)
        except PromiseLimit as e:
            raise GuardRefused("promise_exists", str(e)) from e
        self.calls.clear(call_id, "pending_promise", "borrower_confirmed")
        return {"promise_id": pid, **pending}

    # ---------- R4: payment link ----------

    @_audited("send_payment_link")
    def send_payment_link(self, call_id: str, *, amount: int) -> dict[str, Any]:
        _, loan_id = self._require_identity(call_id)
        self._check_amount(loan_id, amount)
        link = self.ledger.create_payment_link(loan_id=loan_id, amount=amount,
                                               idempotency_key=f"{call_id}:{amount}",
                                               call_id=call_id)
        return {"sent_to": "the borrower's registered mobile number", "amount": amount,
                "link_id": link["id"], "already_sent": link["reused"]}

    # ---------- follow-up, escalation, opt-out ----------

    @_audited("schedule_followup")
    def schedule_followup(self, call_id: str, *, on_date: str, reason: str) -> dict[str, Any]:
        _, loan_id = self._bound(call_id)
        when = _parse_date(on_date)
        if when is None or not self.today() < when <= self.today() + timedelta(
                days=FOLLOWUP_MAX_DAYS):
            raise GuardRefused("bad_followup_date",
                               f"Follow-up must be within the next {FOLLOWUP_MAX_DAYS} days "
                               "(YYYY-MM-DD).")
        return {"followup_id": self.ledger.add_followup(loan_id=loan_id, on_date=when,
                                                        reason=reason[:300], call_id=call_id),
                "on_date": when.isoformat()}

    @_audited("escalate_to_human")
    def escalate_to_human(self, call_id: str, *, reason: str, summary: str) -> dict[str, Any]:
        _, loan_id = self._bound(call_id)
        allowed = list(self.lender.needs_human) + ["wrong_person", "complaint"]
        if reason not in allowed:
            raise GuardRefused("bad_reason", f"reason must be one of: {', '.join(allowed)}")
        eid = self.ledger.add_escalation(loan_id=loan_id, reason=reason, summary=summary[:600],
                                         call_id=call_id)
        self.calls.set_state(call_id, escalated=reason)
        return {"escalation_id": eid, "desk": self.lender.escalation_desk}

    @_audited("opt_out")
    def opt_out(self, call_id: str) -> dict[str, Any]:
        borrower_id, _ = self._bound(call_id)
        self.ledger.set_opted_out(borrower_id)
        self.calls.set_state(call_id, opted_out=True)
        return {"opted_out": True}

    # ---------- R6: what the agent says ----------

    def banned_in(self, text: str) -> list[str]:
        t = (text or "").lower()
        return [p for p in self.lender.banned_phrases if p in t]

    def check_reply(self, call_id: str, text: str) -> list[str]:
        hits = self.banned_in(text)
        if hits:
            self.audit.record(call_id=call_id, tenant_id=self.lender.id, action="reply_blocked",
                              args={"phrases": hits}, outcome="denied",
                              detail="banned_phrase: reply replaced")
        return hits


def _parse_date(text: str | None) -> date | None:
    if not text:
        return None
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
