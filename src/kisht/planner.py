"""The planner agent: decides today's outreach. For every account that is due, the model chooses
a priority, chat or voice, why, and how to approach the borrower. Code then checks each choice
against the contact rules (guard R1) and orders the queue.

The model sees no names or phone numbers: only loan ids and the facts that matter for the decision.
Accounts are sent in batches so a small local model keeps up (one line out per account).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

from kisht.guard import GuardRefused, PolicyGuard
from kisht.ports import ChatModel, ModelUnavailable

BATCH = 12
PRIORITIES = {"high": 0, "medium": 1, "low": 2}

INSTRUCTIONS = """\
You plan today's outreach for a lender's loan-servicing team. For EACH account below, decide:
- priority: high, medium or low (who should be contacted first today)
- channel: chat or voice
- reason: why, in at most 10 words
- approach: how the agent should open, in at most 12 words

Think like an experienced collections lead who is fair to borrowers:
- Early overdue accounts usually come before pre-due reminders; more days past due and a missed
  promise raise priority; an open promise that is not yet due usually means low priority.
- Pre-due reminders are gentle and short; chat is usually enough.
- Voice helps when chat has not worked (several attempts without a reply) or for larger amounts.
- Accounts marked DND must not get voice calls. Accounts marked OPTED_OUT must not be contacted:
  still output a line for them, with priority low.
- Be respectful: approaches never threaten or shame.

Output exactly one line per account, nothing else, in this format:
<loan_id> | <priority> | <channel> | <reason> | <approach>
"""

_LINE = re.compile(r"^\W*(ln_[A-Za-z0-9]+)\s*\|\s*(high|medium|low)\s*\|\s*(chat|voice)\s*\|"
                   r"\s*([^|]*)\|\s*(.*)$", re.IGNORECASE)


@dataclass
class PlanItem:
    loan_id: str
    borrower_id: str
    priority: str
    channel: str
    reason: str
    approach: str
    days_past_due: int


@dataclass
class PlanResult:
    queue: list[PlanItem] = field(default_factory=list)
    blocked: list[tuple[str, str]] = field(default_factory=list)   # (loan_id, guard rule)
    unplanned: list[str] = field(default_factory=list)             # the model left these out
    model_calls: int = 0
    seconds: float = 0.0


class Planner:
    def __init__(self, guard: PolicyGuard, model: ChatModel):
        self.guard = guard
        self.ledger = guard.ledger
        self.lender = guard.lender
        self.model = model

    def facts(self, account: dict, today: date) -> str:
        loan_id = account["loan_id"]
        week_ago = (self.guard.now() - timedelta(days=7)).isoformat()
        recent = self.ledger.contacts_since(account["borrower_id"], week_ago)
        last = recent[-1]["outcome"] if recent and recent[-1]["outcome"] else "none"
        missed = len(self.ledger.missed_promises(loan_id, today))
        open_p = self.ledger.open_promises(loan_id)
        if account["days_past_due"]:
            due = f"OVERDUE {account['days_past_due']}d, Rs {account['overdue_amount']}"
        else:
            days = (date.fromisoformat(account["next_due_date"]) - today).days
            due = f"PRE-DUE in {days}d, Rs {account['next_due_amount']}"
        flags = [f for f, on in (("DND", account["dnd"]), ("OPTED_OUT", account["opted_out"]))
                 if on]
        return (f"{loan_id}: {due}; {account['product']}; lang {account['language']}; "
                f"attempts last 7d: {len(recent)}, last outcome: {last}; "
                f"missed promises: {missed}; open promise: "
                f"{open_p[0]['promised_date'] if open_p else 'none'}"
                + (f"; {' '.join(flags)}" if flags else ""))

    def plan(self, today: date | None = None) -> PlanResult:
        today = today or self.guard.today()
        started = time.perf_counter()
        result = PlanResult()
        accounts = {a["loan_id"]: a for a in self.ledger.due_accounts(self.lender.id, today)}
        decided: dict[str, tuple[str, str, str, str]] = {}
        ids = list(accounts)
        batches = [ids[i:i + BATCH] for i in range(0, len(ids), BATCH)]
        for attempt in range(2):                     # one retry for accounts the model skipped
            for batch in batches:
                self._decide(batch, accounts, today, decided, result)
            missing = [x for x in ids if x not in decided]
            if not missing or attempt == 1:
                break
            self._audit("plan_retry", {"missing": len(missing)}, "error", "model skipped lines")
            batches = [missing[i:i + BATCH // 2] for i in range(0, len(missing), BATCH // 2)]
        for loan_id, account in accounts.items():
            if loan_id not in decided:
                result.unplanned.append(loan_id)
                continue
            priority, channel, reason, approach = decided[loan_id]
            try:
                self.guard.check_contact(account["borrower_id"], channel)
                status = "queued"
            except GuardRefused as e:
                result.blocked.append((loan_id, e.code))
                self._audit("plan_item", {"loan_id": loan_id, "channel": channel}, "denied",
                            f"{e.code}: {e.message}")
                status = f"blocked:{e.code}"
            self.ledger.save_plan_item(plan_date=today, loan_id=loan_id, channel=channel,
                                       priority=priority, reason=reason, approach=approach,
                                       status=status)
            if status == "queued":
                result.queue.append(PlanItem(loan_id, account["borrower_id"], priority, channel,
                                             reason, approach, account["days_past_due"]))
        result.queue.sort(key=lambda p: (PRIORITIES[p.priority], -p.days_past_due))
        result.seconds = time.perf_counter() - started
        self._audit("plan", {"date": today.isoformat(), "accounts": len(accounts),
                             "queued": len(result.queue), "blocked": len(result.blocked),
                             "unplanned": len(result.unplanned)}, "ok", "")
        return result

    def _decide(self, batch: list[str], accounts: dict, today: date, decided: dict,
                result: PlanResult) -> None:
        prompt = (INSTRUCTIONS + f"\nTODAY: {today:%A %Y-%m-%d}\n\nACCOUNTS:\n" +
                  "\n".join(self.facts(accounts[x], today) for x in batch))
        try:
            reply = self.model.complete([{"role": "user", "content": prompt}])
        except ModelUnavailable as e:
            self._audit("plan_batch_failed", {"batch": batch}, "error", str(e)[:200])
            return
        result.model_calls += 1
        for line in (reply.content or "").splitlines():
            m = _LINE.match(line.strip())
            if m and m.group(1) in batch and m.group(1) not in decided:
                decided[m.group(1)] = (m.group(2).lower(), m.group(3).lower(),
                                       m.group(4).strip(), m.group(5).strip())

    def _audit(self, action: str, args: dict, outcome: str, detail: str) -> None:
        self.guard.audit.record(call_id=None, tenant_id=self.lender.id, action=action,
                                args=args, outcome=outcome, detail=detail)
