"""CallSession: one agent session per call (D31).

A session is small: the call id, the business config and its tools. The
conversation lives in the Redis notebook, so any worker can handle the next turn.

One caller turn:
  1. save the caller's words in the notebook
  2. if a booking is waiting and the caller's words are a clear yes -> code books it
     and answers; the model is not called at all (it has no tool for this step)
  3. otherwise ask the model; run any tool calls through the guard; repeat (max 3 rounds)
  4. if the reply says "let me check" or states free times without a schedule tool
     having run -> ask the model once more; if it still states unchecked times,
     ask the caller for service and day instead
  5. if the reply claims a booking that did not happen -> replace it
  6. save the reply in the notebook and return it
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from receptionist.business import Business
from receptionist.confirm import (
    claims_availability,
    claims_booking,
    is_clear_yes,
    safe_reply_instead_of_false_claim,
)
from receptionist.guard import Guard, GuardRefused
from receptionist.model_client import ModelClient, ModelUnavailable
from receptionist.notebook import CallStore
from receptionist.prompt import build_messages
from receptionist.tools import TOOL_SCHEMAS, ToolRunner

MAX_TOOL_ROUNDS = 3

SCHEDULE_TOOLS = {"check_availability", "book_visit"}

# Two replies that must not reach the caller (D31):
#  - "let me check" said without calling a tool: the caller would hear nothing more;
#  - a statement about free times when no schedule tool ran this turn.
# Either way we ask the model once more, adding NUDGE to that one request only
# (it is never saved in the notebook). If the second answer still states
# unchecked free times, the caller hears ASK_SERVICE_AND_DAY instead.
NUDGE = {"role": "user", "content": (
    "[System note, not from the caller] Do not answer from memory. Call check_availability "
    "now (or book_visit if the caller is booking), then answer from the tool result.")}
ASK_SERVICE_AND_DAY = {
    "en": "I'll check the schedule for you. Which service would you like, and on which day?",
    "hi": "Main schedule check karti hoon. Aapko kaunsi service chahiye, aur kis din?",
}

_STALL = re.compile(r"let me (check|see|look)|one moment|please hold|hold on|"
                    r"check kar(te|ti|ta) (hain|hoon|hun)|check karein|wait kijiye|"
                    r"ek (minute|second) (dijiye|ruk)", re.IGNORECASE)

_HINDI_MARKERS = {"hai", "hain", "kya", "kal", "parso", "aaj", "mujhe", "chahiye", "karna",
                  "kar", "haan", "nahi", "nahin", "kitna", "kitne", "kaun", "kab", "mera",
                  "meri", "aap", "aapka", "theek", "ji", "ka", "ki", "ke", "ko", "se"}

FALLBACK = {
    "en": "Sorry, I'm having trouble right now. I'll pass your message to the owner, "
          "who will call you back.",
    "hi": "Maaf kijiye, abhi kuch dikkat hai. Main aapka message owner tak pahuncha dungi, "
          "woh aapko call karenge.",
}
STUCK = {
    "en": "Sorry, I couldn't sort that out. Shall I take a message for the owner?",
    "hi": "Maaf kijiye, main yeh nahi kar paayi. Kya main owner ke liye message le loon?",
}
BOOKED = {
    "en": "Done, it's booked: {summary}. See you then!",
    "hi": "Ho gaya, book kar diya: {summary}. Milte hain!",
}
BOOKING_FAILED = {
    "slot_taken": {
        "en": "Sorry, that time was just taken. Shall I look for another time?",
        "hi": "Maaf kijiye, woh time abhi abhi book ho gaya. Kya main doosra time dekhoon?",
    },
    "default": {
        "en": "Sorry, that booking is no longer possible. Shall I look for another time?",
        "hi": "Maaf kijiye, yeh booking ab possible nahi hai. Kya main doosra time dekhoon?",
    },
}


@dataclass
class TurnResult:
    reply: str
    booked: bool = False
    tool_calls: list[str] = field(default_factory=list)
    model_calls: int = 0
    model_latency_s: float = 0.0
    prompt_tokens: int = 0
    cached_tokens: int = 0
    replaced_false_claim: bool = False
    replaced_unchecked_claim: bool = False
    fallback: bool = False


class CallSession:
    def __init__(self, call_id: str, business: Business, calls: CallStore, guard: Guard,
                 model: ModelClient):
        self.call_id = call_id
        self.business = business
        self.calls = calls
        self.guard = guard
        self.tools = ToolRunner(guard)
        self.model = model

    @classmethod
    def start(cls, business: Business, calls: CallStore, guard: Guard, model: ModelClient,
              called_number: str = "", caller_number: str = "",
              language: str | None = None) -> tuple[CallSession, str]:
        lang = language or business.languages.default
        call_id = calls.start_call(business.business_id, lang, called_number, caller_number)
        session = cls(call_id, business, calls, guard, model)
        greeting = business.greeting[lang]
        calls.append(call_id, {"role": "assistant", "content": greeting})
        return session, greeting

    @property
    def language(self) -> str:
        return self.calls.get(self.call_id, "language", self.business.languages.default)

    def handle(self, caller_text: str) -> TurnResult:
        self.calls.append(self.call_id, {"role": "user", "content": caller_text})
        self._follow_caller_language(caller_text)
        pending = self.calls.get(self.call_id, "pending_booking")
        if pending and is_clear_yes(caller_text):
            return self._finish_booking(pending)

        result = TurnResult(reply="")
        started = time.perf_counter()
        try:
            reply_text = self._run_model(result)
        except ModelUnavailable as e:
            self._log("model_unavailable", {"error": str(e)[:300]}, "error")
            self.calls.set_state(self.call_id, handoff_needed=True)
            result.fallback = True
            reply_text = FALLBACK.get(self.language, FALLBACK["en"])
        result.model_latency_s = time.perf_counter() - started

        already_booked = self.calls.get(self.call_id, "booking_id") is not None
        if not result.fallback and claims_booking(reply_text) and not already_booked:
            pending = self.calls.get(self.call_id, "pending_booking")
            self._log("false_claim_blocked", {"reply": reply_text[:300]}, "denied")
            reply_text = safe_reply_instead_of_false_claim(pending, self.language)
            result.replaced_false_claim = True

        result.reply = reply_text
        self.calls.append(self.call_id, {"role": "assistant", "content": reply_text})
        return result

    def end(self, outcome: str) -> None:
        self.calls.end_call(self.call_id, outcome)

    def _finish_booking(self, pending: dict) -> TurnResult:
        """The caller said yes to the read-back: code books it, with no model call (D43, D44).

        The model has no tool for this step, so it can never book on its own.
        """
        started = time.perf_counter()
        result = TurnResult(reply="", tool_calls=["confirm_booking"])
        self.guard.mark_caller_yes(self.call_id)
        try:
            booked = self.guard.confirm_booking(self.call_id, pending_id=pending["id"])
        except GuardRefused as e:                      # slot just taken, or time moved on
            lines = BOOKING_FAILED.get(e.code, BOOKING_FAILED["default"])
            reply = lines.get(self.language, lines["en"])
        else:
            self.calls.set_state(self.call_id, booking_id=booked["id"])
            result.booked = True
            reply = BOOKED.get(self.language, BOOKED["en"]).format(summary=pending["summary"])
        result.model_latency_s = time.perf_counter() - started
        result.reply = reply
        self.calls.append(self.call_id, {"role": "assistant", "content": reply})
        return result

    def _run_model(self, result: TurnResult) -> str:
        today = self.guard.now().date()
        nudged = False
        checked = False      # did a schedule tool run this turn?
        proposed = None      # read-back from a book_visit that succeeded this turn
        for _ in range(MAX_TOOL_ROUNDS):
            messages = build_messages(self.business, self.calls.messages(self.call_id), today)
            reply = self._ask(messages, result)
            if not reply.tool_calls and not nudged:
                reason = self._needs_a_tool(reply.content, checked)
                if reason:
                    nudged = True
                    self._log(reason, {"reply": reply.content[:600]}, "error")
                    reply = self._ask([*messages, NUDGE], result)   # NUDGE is never saved
            if not reply.tool_calls:
                text = (reply.content or "").strip()
                if not text:
                    break
                if not checked and claims_availability(text):
                    self._log("availability_claim_blocked", {"reply": text[:600]}, "denied")
                    result.replaced_unchecked_claim = True
                    return ASK_SERVICE_AND_DAY.get(self.language, ASK_SERVICE_AND_DAY["en"])
                return text
            self.calls.append(self.call_id, {
                "role": "assistant", "content": reply.content or None,
                "tool_calls": [{"id": tc.id, "type": "function",
                                "function": {"name": tc.name, "arguments": tc.arguments}}
                               for tc in reply.tool_calls]})
            for tc in reply.tool_calls:
                outcome = self.tools.run(self.call_id, tc.name, tc.arguments)
                result.tool_calls.append(tc.name)
                checked = checked or tc.name in SCHEDULE_TOOLS
                if tc.name == "book_visit" and outcome.content.get("ok"):
                    proposed = outcome.content.get("read_back")
                self.calls.append(self.call_id, outcome.as_message(tc.id))
        # Rounds are used up. If the last round proposed a booking, the caller must still
        # hear the read-back (rule 3 says the model would only repeat it anyway); seen live
        # in M5 when check -> check(wrong staff) -> book_visit spent all three rounds.
        if proposed:
            return proposed
        stuck = self.calls.incr(self.call_id, "stuck_count")
        self._log("stuck", {"stuck_count": stuck}, "error")
        return STUCK.get(self.language, STUCK["en"])

    @staticmethod
    def _needs_a_tool(text: str, checked: bool) -> str | None:
        """Why the reply should not reach the caller as it is, or None if it can."""
        if _STALL.search(text or ""):
            return "stall_retry"
        if not checked and claims_availability(text or ""):
            return "unchecked_availability_retry"
        return None

    def _ask(self, messages: list[dict], result: TurnResult):
        reply = self.model.complete(messages, TOOL_SCHEMAS)
        result.model_calls += 1
        result.prompt_tokens += reply.prompt_tokens
        result.cached_tokens += reply.cached_tokens
        return reply

    def _follow_caller_language(self, text: str) -> None:
        """Rough guess, used only for our own fixed lines (fallbacks, safe replies).
        The model picks its reply language itself (prompt rule 7)."""
        words = set(re.findall(r"[a-z]+", text.lower()))
        devanagari = re.search(r"[\u0900-\u097f]", text) is not None     # Sarvam STT (D84)
        if "hi" in self.business.languages.allowed and (devanagari or words & _HINDI_MARKERS):
            self.calls.set_state(self.call_id, language="hi")

    def _log(self, action: str, args: dict, outcome: str) -> None:
        self.guard.audit.record(call_id=self.call_id, business_id=self.business.business_id,
                                action=action, args=args, outcome=outcome)
