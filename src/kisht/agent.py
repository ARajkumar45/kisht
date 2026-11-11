"""The conversation agent: one per conversation, holding nothing that matters in memory (the
transcript and state live in CallState, so any worker can take the next turn).

One borrower turn:
  1. save the borrower's words; follow their language
  2. if a promise is waiting and the words are a clear yes -> code saves it (the model has no
     tool for this), then the model continues (e.g. schedules a follow-up, closes)
  3. otherwise the model plans and acts: it may call several tools in a row (verify identity,
     read dues, send a link, escalate ...), up to MAX_TOOL_ROUNDS; every call passes the guard
  4. before anything is said, code checks the reply: banned phrases, money mentioned before
     identity is verified, claims only code can make (promise saved, waiver, payment received),
     and "let me check" without a tool; it asks the model once more or replaces the reply
  5. save the reply; report what happened (for evals and telemetry)
"""
from __future__ import annotations

from datetime import date

import re
import time
from dataclasses import dataclass, field
from typing import Any

from kisht.confirm import (
    claims_link_sent,
    claims_payment_received,
    claims_promise_saved,
    claims_waiver,
    is_yes_to_promise,
    leaks_account,
)
from kisht.guard import GuardRefused, PolicyGuard
from kisht.knowledge import Agreement
from kisht.ports import CallState, ChatModel, ModelUnavailable
from kisht.prompt import GREETING, build_messages
from kisht.tools import TOOL_SCHEMAS, ToolRunner

MAX_TOOL_ROUNDS = 6
ENDING_ACTIONS = {"opt_out", "escalate_to_human"}

_STALL = re.compile(r"let me (check|see|look)|one moment|please hold|hold on|"
                    r"check kar(te|ti|ta) (hain|hoon|hun)|check kar rah(a|i|e)|"
                    r"dekh rah(a|i|e) (hoon|hun|hain)|ek (minute|second)|\.\.\.\s*$",
                    re.IGNORECASE)
_HINDI = {"hai", "hain", "kya", "kal", "parso", "aaj", "mujhe", "nahi", "nahin", "haan", "ji",
          "kitna", "mera", "meri", "aap", "theek", "paisa", "paise", "karunga", "karungi",
          "kar", "dunga", "dungi", "abhi", "salary", "tankhwah"}

NOTE = {"role": "user", "content": (
    "[System note, not from the borrower] Do not answer from memory and do not say 'let me "
    "check'. Use the tools now (verify_identity first if not done), then answer from the "
    "results.")}
UNBACKED = {"role": "user", "content": (
    "[System note, not from the borrower] You said you sent or will send a payment link, but "
    "you did not call send_payment_link. Call it now if the borrower wants a link; otherwise "
    "reply again without claiming a link.")}
UNCHECKED_ID = {"role": "user", "content": (
    "[System note, not from the borrower] The borrower just gave a date of birth or PIN code, "
    "but you did not call verify_identity. Only the tool can say whether it matches: call it "
    "now with what they said, then reply from its result.")}
_ID_DETAIL = re.compile(r"\b\d{6}\b|\b\d{1,2}[ ./-]?(st|nd|rd|th)?[ ./-]?"
                        r"([a-z]{3,9}|\d{1,2})[ ,./-]+(19|20)\d{2}\b", re.IGNORECASE)
AFTER_PROMISE = {"role": "user", "content": (
    "[System note, not from the borrower] The promise is saved and the borrower has heard "
    "that. Schedule a follow-up for the day after the promised date with schedule_followup, "
    "then close the conversation warmly in one or two sentences.")}

SAY = {
    "promise_saved": {
        "en": "Thank you, noted: {read_back}.",
        "hi": "Dhanyavaad, note kar liya: {read_back}.",
    },
    "read_back": {
        "en": "So you will pay {read_back}. Is that right?",
        "hi": "Confirm kar doon: {read_back}. Sahi hai?",
    },
    "fallback": {
        "en": "Sorry, I'm having a technical problem. Our team will contact you. Thank you.",
        "hi": "Maaf kijiye, abhi technical dikkat hai. Hamari team aapse sampark karegi. "
              "Dhanyavaad.",
    },
    "stuck": {
        "en": "Sorry, I couldn't sort that out. Shall I ask our team to call you?",
        "hi": "Maaf kijiye, main yeh nahi kar paayi. Kya main team se aapko call karwaun?",
    },
    "verify_first": {
        "en": "Before I can discuss any details, may I have your date of birth or PIN code?",
        "hi": "Kuch bhi details batane se pehle, kya aap apni date of birth ya PIN code bata "
              "sakte hain?",
    },
    "cannot_decide": {
        "en": "I can't decide that myself, but I can pass it to our team with your details. "
              "Shall I do that?",
        "hi": "Yeh main khud decide nahi kar sakti, lekin aapki baat team tak pahuncha sakti "
              "hoon. Kar doon?",
    },
    "polite": {
        "en": "I'm sorry if that came out wrong. I'm here to help you find a way that works "
              "for you.",
        "hi": "Maaf kijiye agar baat galat lagi. Main aapki madad ke liye hoon, aap jaisa "
              "aasaan ho.",
    },
}


@dataclass
class TurnResult:
    reply: str
    tool_calls: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)      # guard rules that said no this turn
    replaced: list[str] = field(default_factory=list)     # why code replaced the model's reply
    promise_saved: bool = False
    ended: str | None = None                              # opt_out / escalate_to_human
    model_calls: int = 0
    model_latency_s: float = 0.0
    queue_wait_s: float = 0.0
    prompt_tokens: int = 0
    cached_tokens: int = 0
    fallback: bool = False


class Agent:
    def __init__(self, call_id: str, guard: PolicyGuard, calls: CallState, model: ChatModel,
                 agreement: Agreement | None = None):
        self.call_id = call_id
        self.guard = guard
        self.lender = guard.lender
        self.calls = calls
        self.model = model
        self.tools = ToolRunner(guard, agreement)

    @classmethod
    def start(cls, *, guard: PolicyGuard, calls: CallState, model: ChatModel, borrower_id: str,
              loan_id: str, channel: str, agreement: Agreement | None = None
              ) -> tuple[Agent, str]:
        """Bind a new conversation to one account (after the contact rules) and greet.
        Raises GuardRefused if the borrower may not be contacted now."""
        borrower = guard.ledger.borrower(borrower_id)
        lang = borrower["language"] if borrower else guard.lender.languages.default
        if lang not in guard.lender.languages.allowed:
            lang = guard.lender.languages.default
        call_id = calls.start_call(guard.lender.id, lang, channel=channel)
        guard.start_contact(call_id, borrower_id=borrower_id, loan_id=loan_id, channel=channel)
        first_name = borrower["name"].split()[0]
        calls.set_state(call_id, first_name=first_name)
        greeting = GREETING.get(lang, GREETING["en"]).format(
            agent=guard.lender.agent_name, lender=_short(guard.lender.name), first_name=first_name)
        calls.append(call_id, {"role": "assistant", "content": greeting})
        return cls(call_id, guard, calls, model, agreement), greeting

    @property
    def language(self) -> str:
        return self.calls.get(self.call_id, "language", self.lender.languages.default)

    def say(self, key: str, **kw: Any) -> str:
        lines = SAY[key]
        return lines.get(self.language, lines["en"]).format(**kw)

    # ---------- one turn ----------

    def handle(self, text: str) -> TurnResult:
        started = time.perf_counter()
        self.calls.append(self.call_id, {"role": "user", "content": text})
        self._follow_language(text)
        result = TurnResult(reply="")
        pending = self.calls.get(self.call_id, "pending_promise")
        extra: list[dict] = []
        prefix = ""
        if pending and is_yes_to_promise(text, pending["amount"],
                                         date.fromisoformat(pending["pay_date"]),
                                         self.guard.today()):
            prefix = self._save_promise(pending, result)
            if result.promise_saved:
                extra = [AFTER_PROMISE]
        try:
            reply = self._run_model(result, extra)
        except ModelUnavailable as e:
            self._log("model_unavailable", {"error": str(e)[:300]}, "error")
            reply, result.fallback = self.say("fallback"), True
        reply = (prefix + " " + reply).strip() if prefix else reply
        result.reply = reply
        result.model_latency_s = time.perf_counter() - started
        self.calls.append(self.call_id, {"role": "assistant", "content": reply})
        return result

    def _save_promise(self, pending: dict, result: TurnResult) -> str:
        self.guard.mark_borrower_yes(self.call_id)
        try:
            saved = self.guard.confirm_promise(self.call_id)
        except GuardRefused as e:
            result.refused.append(e.code)
            return ""
        result.promise_saved = True
        self.calls.set_state(self.call_id, did_save_promise=True)
        return self.say("promise_saved", read_back=saved["read_back"])

    def _run_model(self, result: TurnResult, extra: list[dict]) -> str:
        nudged = False
        for _ in range(MAX_TOOL_ROUNDS):
            messages = self._messages() + extra
            reply = self._ask(messages, result)
            if not reply.tool_calls and not nudged:
                note = self._needs_retry(reply.content or "", result)
                if note:
                    nudged = True
                    reply = self._ask([*messages, note], result)
            if not reply.tool_calls:
                text = (reply.content or "").strip()
                if not text:
                    break
                return self._checked(text, result)
            self.calls.append(self.call_id, {
                "role": "assistant", "content": reply.content or None,
                "tool_calls": [{"id": tc.id, "type": "function",
                                "function": {"name": tc.name, "arguments": tc.arguments}}
                               for tc in reply.tool_calls]})
            for tc in reply.tool_calls:
                out = self.tools.run(self.call_id, tc.name, tc.arguments)
                result.tool_calls.append(tc.name)
                if not out.ok:
                    result.refused.append(out.content.get("refused", "error"))
                else:
                    self.calls.set_state(self.call_id, **{f"did_{tc.name}": True})
                    if tc.name in ENDING_ACTIONS:
                        result.ended = tc.name
                self.calls.append(self.call_id, out.as_message(tc.id))
        self._log("stuck", {}, "error")
        return self.say("stuck")

    def _needs_retry(self, text: str, result: TurnResult) -> dict | None:
        """A reply that promises an action the model has not taken gets one more try."""
        if _STALL.search(text):
            self._log("stall_retry", {"reply": text[:300]}, "error")
            return NOTE
        if (not self.calls.get(self.call_id, "identity_verified", False)
                and "verify_identity" not in result.tool_calls
                and _ID_DETAIL.search(self._last_user_text())):
            self._log("unchecked_identity_retry", {"reply": text[:300]}, "error")
            return UNCHECKED_ID
        if claims_link_sent(text) and "send_payment_link" not in result.tool_calls:
            self._log("unbacked_claim_retry", {"reply": text[:300]}, "error")
            return UNBACKED
        return None

    def _last_user_text(self) -> str:
        for m in reversed(self.calls.messages(self.call_id)):
            if m.get("role") == "user":
                return m.get("content") or ""
        return ""

    def _checked(self, text: str, result: TurnResult) -> str:
        """The last line of defence before anything is said or sent."""
        if self.guard.check_reply(self.call_id, text):
            result.replaced.append("banned_phrase")
            return self.say("polite")
        verified = self.calls.get(self.call_id, "identity_verified", False)
        if not verified and leaks_account(text, self._account_amounts()):
            result.replaced.append("leak_before_identity")
            self._log("leak_blocked", {"reply": text[:300]}, "denied")
            return self.say("verify_first")
        if claims_promise_saved(text) and not result.promise_saved:
            result.replaced.append("false_promise_claim")
            self._log("false_claim_blocked", {"reply": text[:300]}, "denied")
            pending = self.calls.get(self.call_id, "pending_promise")
            return (self.say("read_back", read_back=pending["read_back"]) if pending
                    else self.say("stuck"))
        if claims_link_sent(text) and "send_payment_link" not in result.tool_calls:
            result.replaced.append("unbacked_link_claim")
            self._log("false_claim_blocked", {"reply": text[:300]}, "denied")
            return self.say("stuck")
        if claims_waiver(text) or claims_payment_received(text):
            result.replaced.append("false_claim")
            self._log("false_claim_blocked", {"reply": text[:300]}, "denied")
            return self.say("cannot_decide")
        return text

    # ---------- end of conversation: outcome + case note (memory) ----------

    def outcome(self) -> str:
        st = self.calls.get_state(self.call_id)
        if st.get("did_opt_out"):
            return "opted_out"
        if st.get("escalated"):
            return f"escalated:{st['escalated']}"
        if st.get("did_save_promise"):
            return "promise"
        if st.get("did_send_payment_link"):
            return "link_sent"
        if not st.get("identity_verified"):
            return "not_verified"
        return "talked"

    def finish(self) -> dict[str, str]:
        """Write the case note the next conversation will read (after identity is verified).
        The model summarises; if it cannot, code writes a plain note."""
        outcome = self.outcome()
        lines = [f"{m['role']}: {m['content']}" for m in self.calls.messages(self.call_id)
                 if m["role"] in ("user", "assistant") and m.get("content")]
        note = f"Outcome: {outcome}."
        try:
            reply = self.model.complete([{"role": "user", "content": (
                "Write a case note for the loan-servicing team in at most two sentences, in "
                "English: what the borrower said, what was agreed, what to do next. No phone "
                f"numbers. Outcome code: {outcome}.\n\nCONVERSATION:\n" + "\n".join(lines))}])
            if reply.content.strip():
                note = reply.content.strip()[:500]
        except ModelUnavailable:
            pass
        contact_id = self.calls.get(self.call_id, "contact_id")
        if contact_id:
            self.guard.ledger.close_contact(contact_id, outcome, note)
        self.calls.end_call(self.call_id, outcome)
        return {"outcome": outcome, "note": note}

    # ---------- helpers ----------

    def _account_amounts(self) -> set[int]:
        """This borrower's real amounts, which must not be said before identity is verified."""
        loan_id = self.calls.get(self.call_id, "loan_id")
        if not loan_id:
            return set()
        d = self.guard.ledger.dues(loan_id, self.guard.today())
        loan = self.guard.ledger.loan(loan_id)
        return {x for x in (d.overdue_amount, d.next_due_amount, loan["emi"],
                            d.overdue_amount + d.next_due_amount) if x}

    def _messages(self) -> list[dict]:
        return build_messages(self.lender, self.calls.messages(self.call_id), self.guard.today(),
                              self.calls.get(self.call_id, "first_name", "the borrower"),
                              self.calls.get(self.call_id, "channel", "chat"))

    def _ask(self, messages: list[dict], result: TurnResult):
        reply = self.model.complete(messages, TOOL_SCHEMAS)
        result.model_calls += 1
        result.prompt_tokens += reply.prompt_tokens
        result.cached_tokens += reply.cached_tokens
        result.queue_wait_s += getattr(reply, "queue_wait_s", 0.0)
        return reply

    def _follow_language(self, text: str) -> None:
        if "hi" not in self.lender.languages.allowed:
            return
        words = set(re.findall(r"[a-z]+", text.lower()))
        if re.search(r"[ऀ-ॿ]", text) or len(words & _HINDI) >= 2:
            self.calls.set_state(self.call_id, language="hi")
        elif len(words) >= 4 and not words & _HINDI:
            self.calls.set_state(self.call_id, language="en")

    def _log(self, action: str, args: dict, outcome: str) -> None:
        self.guard.audit.record(call_id=self.call_id, tenant_id=self.lender.id, action=action,
                                args=args, outcome=outcome, detail=action)


def _short(name: str) -> str:
    return name.split(" (")[0].replace(" Ltd", "")
