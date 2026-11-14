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

On a voice call the reply is released sentence by sentence while the model is still writing
(handle(text, on_say=...)): the model starts writing within half a second but needs 2-3 s for
a whole reply, so waiting for the last word wastes most of the turn. Each sentence goes out
only after the reply so far has passed the same checks as in step 4.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from typing import Any

from kisht.audit import mask_digits
from kisht.confirm import (
    asks_about_terms,
    asks_to_stop,
    claims_handed_over,
    claims_link_sent,
    claims_payment_received,
    claims_promise_saved,
    claims_stop_contact,
    claims_waiver,
    is_clear_yes,
    is_plain_talk,
    is_stall,
    is_yes_to_promise,
    leaks_account,
    mentions_hardship,
    names_a_day,
)
from kisht.guard import GuardRefused, PolicyGuard
from kisht.insights import InsightsStore
from kisht.knowledge import Agreement
from kisht.languages import detect, pack
from kisht.languages import say as pack_say
from kisht.ports import CallState, ChatModel, ModelUnavailable
from kisht.prompt import GREETING, build_messages
from kisht.tools import TOOL_SCHEMAS, ToolRunner
from kisht.tracing import call_span, child_span, mark_error, set_attrs

MAX_TOOL_ROUNDS = 6
ENDING_ACTIONS = {"opt_out", "escalate_to_human"}


NOTE = {"role": "user", "content": (
    "[System note, not from the borrower] Do not answer from memory and do not say 'let me "
    "check' or 'I will record it'. Use the tools now (verify_identity first if not done; "
    "record_promise_to_pay if the borrower named a date), then answer from the results.")}
UNBACKED = {"role": "user", "content": (
    "[System note, not from the borrower] You said you sent or will send a payment link, but "
    "you did not call send_payment_link. Call it now if the borrower wants a link; otherwise "
    "reply again without claiming a link.")}
UNCHECKED_ID = {"role": "user", "content": (
    "[System note, not from the borrower] The borrower just gave a date of birth or PIN code, "
    "but you did not call verify_identity. Only the tool can say whether it matches: call it "
    "now with what they said, then reply from its result.")}
NO_OPT_OUT = {"role": "user", "content": (
    "[System note, not from the borrower] You said we will not contact them again, but you "
    "did not call opt_out. Only that tool stops contact: call it now if the borrower asked "
    "for that (no identity check needed); otherwise reply again without that promise.")}
NO_HANDOFF = {"role": "user", "content": (
    "[System note, not from the borrower] You said the case is with our team, but you did "
    "not call escalate_to_human. Only that tool hands a case over: call it now with the "
    "fitting reason and a short summary; otherwise reply again without that claim.")}
OFFER_HINT = (" You just offered a call from our team. If the borrower accepts, call "
              "escalate_to_human now; if they decline, carry on.")
REPEATING = {"role": "user", "content": (
    "[System note, not from the borrower] You have already said almost exactly this and it "
    "did not move the conversation. Do not repeat it. If the borrower cannot pay even the "
    "minimum, is in hardship, disputes the amount, or wants something you cannot decide, call "
    "escalate_to_human now. Otherwise take a different next step.")}
TERMS_HINT = (" The borrower asked about the loan's terms: call lookup_agreement now and "
              "answer from it, naming the section number. This needs no identity check.")
HARDSHIP_HINT = (" The borrower spoke of hardship (job loss, illness or a death). Do not "
                 "bargain: show care, and call escalate_to_human with reason hardship unless "
                 "they themselves offer to pay.")
HARDSHIP_TURNS = 2
CUE_NOTE = "[System note, not from the borrower]"
NO_PROMISE = {"role": "user", "content": (
    "[System note, not from the borrower] The borrower named a day. If they mean to pay on "
    "that day, call record_promise_to_pay now with that date and the amount (the full "
    "overdue amount if they named none); the tool's read_back is your reply. If they did "
    "not promise to pay, carry on.")}
LANGUAGE_HINT = "[System note, not from the borrower] Reply in {name}."
SAME_REPLY = 0.9          # two replies this alike count as a repeat
# The second try after these may be made to call the tool (where the model server allows it).
FORCED_TOOL = {"unbacked_claim_retry": "send_payment_link",
               "unbacked_handoff_retry": "escalate_to_human",
               "unchecked_identity_retry": "verify_identity"}
ID_HINT = {"role": "user", "content": (
    "[System note, not from the borrower] If the borrower just gave a date of birth or PIN "
    "code, call verify_identity with it now, before replying.")}
_ID_DETAIL = re.compile(r"\b\d{6}\b|\b(19[4-9]\d|200\d)\b")   # a PIN, or a birth year
COACH = ("[Private note from your supervisor, not from the borrower] {note}\nFollow it in your "
         "next reply if your rules allow. Never mention the supervisor or this note.")
AFTER_PROMISE = {"role": "user", "content": (
    "[System note, not from the borrower] The promise is saved and the borrower has heard "
    "that. Schedule a follow-up for the day after the promised date with schedule_followup, "
    "then close the conversation warmly in one or two sentences.")}



_SENTENCE_END = re.compile(r"(?<!\bRs)(?<!\bMr)(?<!\bDr)(?<!\bNo)[.!?\u0964](?=\s)")
MIN_PIECE = 12            # characters; shorter bits wait for the next sentence


class CallerGone(Exception):
    """On a call: the caller spoke over the agent or hung up, so this turn is abandoned."""


class _Out:
    """What the borrower has heard so far in this turn, in order."""

    def __init__(self, on_say: Any):
        self.on_say = on_say
        self.pieces: list[tuple[str, bool]] = []      # (text, is a filler line)
        self.committed = 0                            # pieces already saved in the transcript
        self.done = False                             # the model's own reply went out through here
        self.started = time.perf_counter()
        self.first_s: float | None = None

    def __call__(self, piece: str, filler: bool = False) -> None:
        piece = (piece or "").strip()
        if not piece:
            return
        if self.first_s is None:
            self.first_s = time.perf_counter() - self.started
        self.pieces.append((piece, filler))
        self.on_say(piece)

    def commit(self) -> None:
        self.committed = len(self.pieces)

    def still_listening(self) -> None:
        """Raises CallerGone if the voice layer says the caller has cut in. Asked before any
        tool runs: a link must not be sent, or a case opened, for a turn the caller already
        talked over (before, this was only noticed at the next spoken sentence)."""
        alive = getattr(self.on_say, "alive", None)
        if alive is not None and not alive():
            raise CallerGone

    def text(self) -> str:
        return " ".join(p for p, _ in self.pieces)

    def uncommitted(self) -> str:
        return " ".join(p for p, filler in self.pieces[self.committed:] if not filler)


class _Speaker:
    """Releases the start of a model reply while the rest is still being written. A sentence
    goes out early only if the reply up to and including it is plain talk (no number, no word
    about an action) and passes every check a whole reply must pass. From the first sentence
    that is not, everything waits until the model has finished: if a tool call follows, that
    text is dropped, as it always was; if not, the whole reply is checked and said."""

    def __init__(self, agent: Agent, result: TurnResult, out: _Out, check_retry: bool):
        self.agent, self.result, self.out, self.check_retry = agent, result, out, check_retry
        self.quiet = result.promise_saved    # after "your promise is saved", no "sorry" line
        self.text = ""
        self.said = 0             # characters of self.text already released
        self.stopped = False

    def feed(self, piece: str) -> None:
        if self.stopped:
            return
        self.text += piece
        if "<think" in self.text or "<tool_call" in self.text:
            self.stopped = True
            return
        end = None
        for m in _SENTENCE_END.finditer(self.text, self.said):
            end = m.end()
        if end is None or end - self.said < MIN_PIECE:
            return
        ready = self.text[:end]
        # The model is never cut off here, even when this reply will be asked again ("I am
        # recording it" with no tool yet): tried live, and the cut sometimes removed the very
        # tool call that was about to follow the words.
        if (not is_plain_talk(ready) or self.agent._violation(ready, self.result)
                or (self.check_retry and self.agent._retry_reason(ready, self.result))):
            self.stopped = True          # the rest waits for the whole reply and its checks
            return
        self.out(self.text[self.said:end])
        self.said = end

    def heard(self) -> str:
        return self.text[:self.said].strip()

    def finish(self, full: str) -> str:
        """The model has finished: check the whole reply, release what is left."""
        heard = self.heard()
        checked = self.agent._checked(full, self.result)
        if checked == full and full.startswith(heard):
            self.out(full[len(heard):])
            self.out.done = True
            return full
        if not heard:
            return checked        # nothing was heard: the caller says the safe line instead
        # The clean start was heard; the blocked rest is replaced by the safe line (seen
        # live without it: the borrower heard only "Okay, Sunita." and then silence).
        self.out.done = True
        if not self.quiet:
            self.out(checked)
            return f"{heard} {checked}"
        return heard


@dataclass
class TurnResult:
    reply: str
    tool_calls: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)      # guard rules that said no this turn
    replaced: list[str] = field(default_factory=list)     # why code replaced the model's reply
    blocked: list[str] = field(default_factory=list)      # the model's words that were replaced
    promise_saved: bool = False
    ended: str | None = None                              # opt_out / escalate_to_human
    model_calls: int = 0
    model_latency_s: float = 0.0
    queue_wait_s: float = 0.0
    prompt_tokens: int = 0
    cached_tokens: int = 0
    fallback: bool = False
    coach: str | None = None                              # supervisor's note used this turn
    first_say_s: float | None = None                      # voice: seconds until the first words


class Agent:
    def __init__(self, call_id: str, guard: PolicyGuard, calls: CallState, model: ChatModel,
                 agreement: Agreement | None = None, insights: InsightsStore | None = None):
        self.call_id = call_id
        self.insights = insights
        self.guard = guard
        self.lender = guard.lender
        self.calls = calls
        self.model = model
        self._lead: tuple[int, dict] | None = None     # this turn's language note
        self._force: str | None = None      # tool the second try must call
        self.tools = ToolRunner(guard, agreement)
        self._amounts: set[int] | None = None

    @classmethod
    def start(cls, *, guard: PolicyGuard, calls: CallState, model: ChatModel, borrower_id: str,
              loan_id: str, channel: str, agreement: Agreement | None = None,
              insights: InsightsStore | None = None, source: str = "live",
              warm: bool = True) -> tuple[Agent, str]:
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
        greeting = greeting_for(guard.lender, lang, first_name, channel)
        calls.append(call_id, {"role": "assistant", "content": greeting})
        if insights:
            insights.open_call(call_id=call_id, lender_id=guard.lender.id,
                               borrower_id=borrower_id, loan_id=loan_id,
                               borrower_name=borrower["name"] if borrower else None,
                               channel=channel, language=lang, greeting=greeting, source=source)
        agent = cls(call_id, guard, calls, model, agreement, insights)
        if warm:
            agent._warm()
        return agent, greeting

    def _warm(self) -> None:
        """Have the model server read the instructions while the greeting is being heard, so
        the borrower's first words do not wait for it (measured: 6 s cold, 2 s warm). The
        placeholder borrower turn is needed: the server refuses a prompt that ends with the
        agent speaking. Reading takes about 4 s, which the greeting and the answer cover."""
        warm = getattr(self.model, "warm", None)
        if warm:
            messages = [*self._messages(), {"role": "user", "content": "."}]
            threading.Thread(target=warm, args=(messages, TOOL_SCHEMAS), daemon=True).start()

    @property
    def language(self) -> str:
        return self.calls.get(self.call_id, "language", self.lender.languages.default)

    def say(self, key: str, **kw: Any) -> str:
        return pack_say(self.language, key, **kw)

    # ---------- one turn ----------

    def handle(self, text: str, on_say: Any = None) -> TurnResult:
        """One borrower turn. With on_say (voice), each checked sentence is handed over as
        soon as it is ready; the returned reply is everything that was said."""
        with call_span(self.call_id, "turn", kisht__channel=self.calls.get(
                self.call_id, "channel", "chat")) as span:
            was_verified = self.calls.get(self.call_id, "identity_verified", False)
            result = self._handle(text, _Out(on_say) if on_say else None)
            set_attrs(span, kisht__language=self.language, kisht__tools=result.tool_calls,
                      kisht__first_say_s=(round(result.first_say_s, 2)
                                          if result.first_say_s is not None else None),
                      kisht__refused=result.refused, kisht__replaced=result.replaced,
                      kisht__promise_saved=result.promise_saved, kisht__ended=result.ended,
                      kisht__model_calls=result.model_calls, kisht__fallback=result.fallback,
                      kisht__coached=bool(result.coach) or None)
            if result.fallback:
                mark_error(span, "model unavailable")
        if self.insights:
            # The call log is read by supervisors and reviewers; a date of birth or PIN code
            # has no business there. The live conversation state (Redis, expiring) keeps it.
            identity_answer = "verify_identity" in result.tool_calls or (
                not was_verified and _ID_DETAIL.search(text))
            self.insights.add_turn(
                self.call_id, borrower=mask_digits(text) if identity_answer else text,
                agent=result.reply, language=self.language, coach=result.coach,
                tools=result.tool_calls, refused=result.refused, replaced=result.replaced,
                seconds=round(result.model_latency_s, 2), model_calls=result.model_calls,
                prompt_tokens=result.prompt_tokens, cached_tokens=result.cached_tokens,
                first_s=(round(result.first_say_s, 2) if result.first_say_s is not None
                         else None))
        return result

    def _handle(self, text: str, out: _Out | None = None) -> TurnResult:
        started = time.perf_counter()
        self._amounts = None
        self.calls.append(self.call_id, {"role": "user", "content": text})
        self._follow_language(text)
        result = TurnResult(reply="")
        if self.calls.get(self.call_id, "takeover"):
            # A supervisor took this conversation over: the model is not asked again.
            result.reply, result.ended = self.say("handover"), "escalate_to_human"
            self.calls.append(self.call_id, {"role": "assistant", "content": result.reply})
            if out:
                out(result.reply)
            return result
        if asks_to_stop(text) and not self.calls.get(self.call_id, "opted_out", False):
            # "Stop calling me" is not left to the model: the eval showed it agreeing in words
            # and recording nothing. Code records the opt-out and says so; no model call.
            done = self.tools.run(self.call_id, "opt_out", "{}")
            result.tool_calls.append("opt_out")
            self._log("opt_out_by_code", {"said": text[:200]}, "ok" if done.ok else "error")
            if done.ok:
                self.calls.set_state(self.call_id, did_opt_out=True)
                result.ended = "opt_out"
                return self._say_now(result, self.say("opted_out"), out)
            result.tool_calls.pop()      # could not record it: let the model handle the turn
        if self._last_agent_text() in self._offers() and is_clear_yes(text, self.language):
            # The agent offered a call from the team and the borrower said yes. Seen in the
            # eval: the model then carried on talking and no case was ever opened.
            return self._say_now(result, self._callback(
                result, "The borrower accepted the offer of a call from the team."), out)
        pending = self.calls.get(self.call_id, "pending_promise")
        st = self.calls.get_state(self.call_id)
        if (st.get("hardship_mentioned") and st.get("identity_verified")
                and not (st.get("escalated") or pending or st.get("did_save_promise"))):
            # Seen in the full run: the model told a borrower who had lost her job "we can
            # plan for 5 December" six turns running and never handed over. The model gets
            # HARDSHIP_TURNS replies after identity is checked; then code hands over.
            waited = st.get("hardship_turns", 0)
            if waited + 1 >= HARDSHIP_TURNS:     # the turn of the mention was the first
                return self._say_now(result, self._callback(
                    result, "The borrower spoke of hardship and the agent did not hand the "
                            "case over."), out)
            self.calls.set_state(self.call_id, hardship_turns=waited + 1)
        # Seen in the eval: half the English conversations got a Hindi reply at some point.
        # Code already follows the borrower's language; the model is told which it is.
        # Two cues from the borrower's words ride along: the eval showed the model answering
        # fee questions from memory and bargaining with borrowers who had lost a job.
        # The language note sits just before the borrower's message, never after it: as the
        # last message it made the model talk instead of act (43 "link sent" lines with no
        # link in 55 conversations).
        at = len(self._built_messages()) - 1
        self._lead = (at, {"role": "user",
                           "content": LANGUAGE_HINT.format(name=pack(self.language).name)})
        hint = ""
        if asks_about_terms(text):
            hint += TERMS_HINT
        if mentions_hardship(text):
            self.calls.set_state(self.call_id, hardship_mentioned=True)
        if (self.calls.get(self.call_id, "hardship_mentioned", False)
                and not self.calls.get(self.call_id, "escalated")):
            hint += HARDSHIP_HINT          # stays until the case is handed over
        if self._last_agent_text() in self._offers():
            hint += OFFER_HINT
        extra: list[dict] = ([{"role": "user", "content": CUE_NOTE + hint}] if hint else [])
        if (not self.calls.get(self.call_id, "identity_verified", False)
                and _ID_DETAIL.search(text)):
            # Seen live: the model answered a date of birth in words, was told to use the
            # tool, and only then called it. Saying so up front saves that wasted round.
            extra.append(ID_HINT)
        note = self.calls.get(self.call_id, "supervisor_note")
        if note:
            self.calls.clear(self.call_id, "supervisor_note")
            result.coach = note
            extra.append({"role": "user", "content": COACH.format(note=note)})
        prefix = ""
        if pending and is_yes_to_promise(text, pending["amount"],
                                         date.fromisoformat(pending["pay_date"]),
                                         self.guard.today(), self.language):
            prefix = self._save_promise(pending, result)
            if result.promise_saved:
                extra = [*extra, AFTER_PROMISE]
            if out:
                out(prefix)              # "your promise is saved" needs no model: say it now
        try:
            reply = self._run_model(result, extra, out)
        except ModelUnavailable as e:
            self._log("model_unavailable", {"error": str(e)[:300]}, "error")
            reply, result.fallback = self.say("fallback"), True
        if prefix and (result.replaced or result.fallback):
            # The promise is saved and confirmed; a blocked or failed closing line would only
            # confuse ("noted ... sorry, I couldn't do that"). Seen in the simulated day.
            reply = prefix
        else:
            if out and not out.done:
                out(reply)               # a line chosen by code: safe line, read-back, fallback
            reply = (prefix + " " + reply).strip() if prefix else reply
        if out:
            # The transcript holds what was said since the last saved part, without filler
            # lines (the model must not learn to say "one moment" itself).
            reply = out.uncommitted() or reply
            result.first_say_s = out.first_s
        result.reply = out.text() if out and out.pieces else reply
        result.model_latency_s = time.perf_counter() - started
        self.calls.append(self.call_id, {"role": "assistant", "content": reply})
        return result

    def _save_promise(self, pending: dict, result: TurnResult) -> str:
        with child_span("save_promise", kisht__amount=pending["amount"],
                        kisht__pay_date=pending["pay_date"]) as span:
            text = self._save_promise_inner(pending, result)
            set_attrs(span, kisht__saved=result.promise_saved)
            return text

    def _save_promise_inner(self, pending: dict, result: TurnResult) -> str:
        self.guard.mark_borrower_yes(self.call_id)
        try:
            saved = self.guard.confirm_promise(self.call_id)
        except GuardRefused as e:
            result.refused.append(e.code)
            return ""
        result.promise_saved = True
        self.calls.set_state(self.call_id, did_save_promise=True)
        return self.say("promise_saved", read_back=saved["read_back"])

    def _run_model(self, result: TurnResult, extra: list[dict],
                   out: _Out | None = None) -> str:
        nudged = False
        seen: set[tuple[str, str]] = set()
        for _ in range(MAX_TOOL_ROUNDS):
            messages = self._messages() + extra
            speaker = _Speaker(self, result, out, check_retry=not nudged) if out else None
            reply = self._ask(messages, result, speaker=speaker)
            if not reply.tool_calls and not nudged:
                note = self._needs_retry(reply.content or "", result)
                if note:
                    nudged = True
                    if speaker and speaker.heard():
                        # Part of the reply was already heard: keep it, and continue from it.
                        self.calls.append(self.call_id, {"role": "assistant",
                                                         "content": speaker.heard()})
                        out.commit()
                        messages = self._messages() + extra
                    speaker = _Speaker(self, result, out, check_retry=False) if out else None
                    reply = self._ask([*messages, note], result, retry=True, speaker=speaker,
                                      force=self._force)
            if not reply.tool_calls:
                text = (reply.content or "").strip()
                if not text:
                    break
                return speaker.finish(text) if speaker else self._checked(text, result)
            if out:
                if speaker and speaker.heard():
                    out.commit()         # saved below, with the tool calls
                elif not out.pieces:
                    # A tool turn needs a second model call (about 2 s more): say so first.
                    out(self.say("moment"), filler=True)
            calls = {(tc.name, tc.arguments) for tc in reply.tool_calls}
            if calls <= seen:
                # The model is repeating calls it already made this turn (seen live in Telugu:
                # promise + link, three times over). Stop the loop instead of burning rounds.
                self._log("repeated_tool_calls", {"calls": sorted(n for n, _ in calls)}, "error")
                pending = self.calls.get(self.call_id, "pending_promise")
                return (self.say("read_back", read_back=pending["read_back"]) if pending
                        else self._stuck(result))
            seen |= calls
            if out:
                out.still_listening()
            self.calls.append(self.call_id, {
                "role": "assistant", "content": reply.content or None,
                "tool_calls": [{"id": tc.id, "type": "function",
                                "function": {"name": tc.name, "arguments": tc.arguments}}
                               for tc in reply.tool_calls]})
            for tc in reply.tool_calls:
                with child_span("execute_tool", gen_ai__operation__name="execute_tool",
                                gen_ai__tool__name=tc.name) as span:
                    done = self.tools.run(self.call_id, tc.name, tc.arguments)
                    set_attrs(span, kisht__ok=done.ok,
                              kisht__refused=None if done.ok else done.content.get("refused"))
                    if not done.ok:
                        mark_error(span, str(done.content.get("refused", "error")))
                result.tool_calls.append(tc.name)
                if not done.ok:
                    result.refused.append(done.content.get("refused", "error"))
                else:
                    self.calls.set_state(self.call_id, **{f"did_{tc.name}": True})
                    if tc.name in ENDING_ACTIONS:
                        result.ended = tc.name
                self.calls.append(self.call_id, done.as_message(tc.id))
        self._log("stuck", {}, "error")
        return self._stuck(result)

    # ---------- when the model cannot finish: code does, or hands over ----------

    def _say_now(self, result: TurnResult, reply: str, out: _Out | None) -> TurnResult:
        """A turn code answers by itself: no model call."""
        result.reply = reply
        self.calls.append(self.call_id, {"role": "assistant", "content": reply})
        if out:
            out(reply)
        return result

    def _offers(self) -> tuple[str, str]:
        """The two lines that offer a call from the team."""
        return self.say("stuck"), self.say("cannot_decide")

    def _stuck(self, result: TurnResult, key: str = "stuck") -> str:
        """The offer of a team call is made once. Seen in the eval: the same offer five turns
        running, the borrower saying yes each time, and nothing behind it. If the last thing
        the agent said was already that offer, code opens the case and says so."""
        if self._last_agent_text() in self._offers():
            return self._callback(result, "The agent could not finish what the borrower asked "
                                          "for, twice in a row.")
        return self.say(key)

    def _callback(self, result: TurnResult, why: str) -> str:
        """Code hands the case to the human desk, then says so: the sentence is true because
        the case exists first."""
        if not self.calls.get(self.call_id, "escalated"):
            summary = f"{why} The borrower's last words: {self._last_user_text()[:300]}"
            try:
                if self.calls.get(self.call_id, "hardship_mentioned", False):
                    self.guard.escalate_to_human(self.call_id, reason="hardship",
                                                 summary=summary)
                else:
                    self.guard.request_callback(self.call_id, summary=summary)
            except GuardRefused:
                return self.say("stuck")
            result.tool_calls.append("escalate_to_human")
            self.calls.set_state(self.call_id, did_escalate_to_human=True)
            self._log("handoff_by_code", {"why": why}, "ok")
        result.ended = "escalate_to_human"
        return self.say("team_will_call")

    def _ask_promise(self, result: TurnResult) -> str:
        """The model said a promise is saved and none is. Seen in the full run: the offer of a
        team call here, twice, sent 16 borrowers who only wanted to name a date to the human
        desk. Code asks the one question a promise needs; only if that was already the last
        thing said does the offer follow."""
        ask = self.say("promise_ask")
        return self._stuck(result) if self._last_agent_text() == ask else ask

    def _hardship_handover(self, result: TurnResult) -> str | None:
        """A borrower in hardship is never sent a link or asked for a date by code: the case
        goes to the human desk."""
        if (self.calls.get(self.call_id, "hardship_mentioned", False)
                and not self.calls.get(self.call_id, "escalated")):
            return self._callback(result, "The borrower spoke of hardship and the agent did "
                                          "not hand the case over.")
        return None

    def _act_on_claim(self, code: str, result: TurnResult) -> str | None:
        """The model said it did something and did not call the tool. For two actions code
        can do it itself, through the same guard, and then say a sentence built from the
        result: a payment link for what is due, and a hand-over to the team. Everything else
        (a promise needs an amount and a date; an opt-out must come from the borrower's own
        words) is not guessed. None means: could not, say the safe line."""
        if code == "unbacked_handoff_claim":
            return self._callback(result, "The agent told the borrower the case is with the "
                                          "team.")
        if code == "unbacked_link_claim":
            if self._could_promise() and names_a_day(self._last_user_text()):
                # Seen in the full run (13 conversations): the borrower said "I will pay on
                # the 14th", the model said "sending the link for the 14th", code sent a link
                # and the promise was never recorded. A named day means a promise: ask for it.
                return self._ask_promise(result)
            loan_id = self.calls.get(self.call_id, "loan_id")
            dues = self.guard.ledger.dues(loan_id, self.guard.today()) if loan_id else None
            amount = (dues.overdue_amount or dues.next_due_amount) if dues else 0
            if not amount:
                return None
            done = self.tools.run(self.call_id, "send_payment_link",
                                  json.dumps({"amount": amount}))
            if not done.ok:
                return None
            result.tool_calls.append("send_payment_link")
            self.calls.set_state(self.call_id, did_send_payment_link=True)
            self._log("link_by_code", {"amount": amount}, "ok")
            return self.say("link_sent", amount=f"{amount:,}")
        return None

    def _needs_retry(self, text: str, result: TurnResult) -> dict | None:
        """A reply that promises an action the model has not taken gets one more try."""
        reason = self._retry_reason(text, result)
        if reason is None:
            return None
        self._log(reason[0], {"reply": text[:300]}, "error")
        self._force = FORCED_TOOL.get(reason[0])
        return reason[1]

    def _retry_reason(self, text: str, result: TurnResult) -> tuple[str, dict] | None:
        if is_stall(text):
            return "stall_retry", NOTE
        if (not self.calls.get(self.call_id, "identity_verified", False)
                and "verify_identity" not in result.tool_calls
                and _ID_DETAIL.search(self._last_user_text())):
            return "unchecked_identity_retry", UNCHECKED_ID
        if claims_link_sent(text) and "send_payment_link" not in result.tool_calls:
            return "unbacked_claim_retry", UNBACKED
        if (claims_promise_saved(text) and not self._promise_backed(result)
                and not self.calls.get(self.call_id, "pending_promise")):
            # Seen live: "maine record kar liya hai" with no tool call and no promise waiting.
            # It would be blocked anyway; one more try can bring the real tool call. (With a
            # promise waiting, the read-back is the right answer and needs no model.)
            return "false_claim_retry", NOTE
        if claims_handed_over(text) and not self._handed_over(result):
            # Seen in the eval: "I am forwarding this to our team", four turns running, and
            # no escalation ever made.
            return "unbacked_handoff_retry", NO_HANDOFF
        if claims_stop_contact(text) and not self._opted_out(result):
            # Seen in the eval: "I will not contact you again", nothing recorded, call over.
            return "unbacked_optout_retry", NO_OPT_OUT
        if (not result.tool_calls and self._could_promise()
                and names_a_day(self._last_user_text())):
            # Seen in the eval, the most common failure: the borrower says "I'll pay on the
            # 14th" and the model chats on without recording it.
            return "unrecorded_promise_retry", NO_PROMISE
        if not result.tool_calls and self._said_before(text):
            # Seen in the eval: the same refusal five times to a borrower in hardship.
            return "repeat_retry", REPEATING
        return None

    def _promise_backed(self, result: TurnResult) -> bool:
        """True in the turn a promise is saved, and afterwards while no new one is waiting:
        "your promise is saved", said again later, is a fact, not a claim."""
        return result.promise_saved or (
            bool(self.calls.get(self.call_id, "did_save_promise", False))
            and not self.calls.get(self.call_id, "pending_promise"))

    def _could_promise(self) -> bool:
        st = self.calls.get_state(self.call_id)
        return bool(st.get("identity_verified")) and not (
            st.get("pending_promise") or st.get("did_save_promise") or st.get("escalated")
            or st.get("hardship_mentioned"))

    def _handed_over(self, result: TurnResult) -> bool:
        return ("escalate_to_human" in result.tool_calls
                or bool(self.calls.get(self.call_id, "escalated")))

    def _last_agent_text(self) -> str:
        for m in reversed(self.calls.messages(self.call_id)):
            if m.get("role") == "assistant":
                return m.get("content") or ""
        return ""

    def _opted_out(self, result: TurnResult) -> bool:
        return ("opt_out" in result.tool_calls
                or bool(self.calls.get(self.call_id, "opted_out", False)))

    def _said_before(self, text: str) -> bool:
        new = " ".join(text.lower().split())
        if len(new) < 60:
            return False
        said = [m.get("content") or "" for m in self.calls.messages(self.call_id)
                if m.get("role") == "assistant"][-3:]
        return any(SequenceMatcher(None, new, " ".join(s.lower().split())).ratio() >= SAME_REPLY
                   for s in said)

    def _last_user_text(self) -> str:
        for m in reversed(self.calls.messages(self.call_id)):
            if m.get("role") == "user":
                return m.get("content") or ""
        return ""

    def _checked(self, text: str, result: TurnResult) -> str:
        """The last line of defence before anything is said or sent."""
        with child_span("reply_check") as span:
            before = len(result.replaced)
            out = self._checked_inner(text, result)
            set_attrs(span, kisht__replaced=result.replaced[before:] or None)
            return out

    def _violation(self, text: str, result: TurnResult) -> str | None:
        """The rule this text breaks, if any. Changes nothing, so it can run on every sentence."""
        if self.guard.banned_in(text):
            return "banned_phrase"
        verified = self.calls.get(self.call_id, "identity_verified", False)
        if not verified and leaks_account(text, self._account_amounts()):
            return "leak_before_identity"
        if not verified and _ID_DETAIL.search(text):
            # Seen live: "is your date of birth 1990-05-15?" (invented). The agent asks for
            # the detail; it never offers one, real or not.
            return "guessed_identity"
        if claims_promise_saved(text) and not self._promise_backed(result):
            return "false_promise_claim"
        if claims_link_sent(text) and "send_payment_link" not in result.tool_calls:
            return "unbacked_link_claim"
        if claims_waiver(text) or claims_payment_received(text):
            return "false_claim"
        if claims_stop_contact(text) and not self._opted_out(result):
            return "unbacked_optout_claim"
        if claims_handed_over(text) and not self._handed_over(result):
            return "unbacked_handoff_claim"
        return None

    def _checked_inner(self, text: str, result: TurnResult) -> str:
        code = self._violation(text, result)
        if code is None:
            return text
        result.replaced.append(code)
        result.blocked.append(text[:400])
        if code == "banned_phrase":
            self.guard.check_reply(self.call_id, text)          # writes the audit entry
            return self.say("polite")
        self._log("false_claim_blocked" if code.startswith(("false", "unbacked"))
                  else "leak_blocked", {"reply": text[:300]}, "denied")
        if code in ("leak_before_identity", "guessed_identity"):
            return self.say("verify_first")
        if code == "false_promise_claim":
            pending = self.calls.get(self.call_id, "pending_promise")
            if pending:
                return self.say("read_back", read_back=pending["read_back"])
            return self._hardship_handover(result) or self._ask_promise(result)
        if code == "false_claim" and claims_payment_received(text) and not claims_waiver(text):
            # Seen in the first run after D114: the borrower says "I have paid", the model
            # answers "your payment is complete" (it cannot know), and the blocked reply became
            # an offer of a team call, which then opened a case for someone who had just paid.
            # There is nothing to decide here: say what is true and stop.
            return self.say("payment_pending")
        # Not after "your promise is saved": that closing line stays alone (see _handle), so
        # an action taken here would never be told to the borrower.
        acted = None if result.promise_saved else (
            self._hardship_handover(result) or self._act_on_claim(code, result))
        if acted:
            return acted
        if (code == "unbacked_link_claim"
                and not self.calls.get(self.call_id, "identity_verified", False)):
            return self.say("verify_first")       # a link needs identity first: ask for it
        return self._stuck(result, "stuck" if code in ("unbacked_link_claim",
                                                       "unbacked_optout_claim")
                           else "cannot_decide")

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
            with call_span(self.call_id, "case_note", kisht__outcome=outcome):
                reply = self.model.complete([{"role": "user", "content": (
                    "Write a case note for the loan-servicing team in at most two sentences, "
                    "in English: what the borrower said, what was agreed, what to do next. No "
                    f"phone numbers. Outcome code: {outcome}.\n\nCONVERSATION:\n" + "\n".join(lines))}])
            if reply.content.strip():
                note = reply.content.strip()[:500]
        except ModelUnavailable:
            pass
        contact_id = self.calls.get(self.call_id, "contact_id")
        if contact_id:
            self.guard.ledger.close_contact(contact_id, outcome, note)
        self.calls.end_call(self.call_id, outcome)
        if self.insights:
            self.insights.close_call(self.call_id, outcome=outcome, note=note)
        return {"outcome": outcome, "note": note}

    # ---------- helpers ----------

    def _account_amounts(self) -> set[int]:
        """This borrower's real amounts, which must not be said before identity is verified."""
        if self._amounts is None:        # read once per turn: checked for every sentence
            loan_id = self.calls.get(self.call_id, "loan_id")
            if not loan_id:
                return set()
            d = self.guard.ledger.dues(loan_id, self.guard.today())
            loan = self.guard.ledger.loan(loan_id)
            self._amounts = {x for x in (d.overdue_amount, d.next_due_amount, loan["emi"],
                                         d.overdue_amount + d.next_due_amount) if x}
        return self._amounts

    def _messages(self) -> list[dict]:
        out = self._built_messages()
        lead = self._lead
        if lead and lead[0] <= len(out):
            out.insert(lead[0], lead[1])
        return out

    def _built_messages(self) -> list[dict]:
        return build_messages(self.lender, self.calls.messages(self.call_id), self.guard.today(),
                              self.calls.get(self.call_id, "first_name", "the borrower"),
                              self.calls.get(self.call_id, "channel", "chat"))

    def _ask(self, messages: list[dict], result: TurnResult, retry: bool = False,
             speaker: _Speaker | None = None, force: str | None = None):
        with child_span("chat", gen_ai__operation__name="chat",
                        gen_ai__request__model=getattr(self.model, "name", "model"),
                        kisht__retry=retry or None) as span:
            try:
                stream = getattr(self.model, "stream", None) if speaker else None
                # Only a model that says it accepts a forced tool is sent one.
                kw = ({"tool_choice": force}
                      if force and getattr(self.model, "force_tools", False) else {})
                reply = (stream(messages, TOOL_SCHEMAS, on_text=speaker.feed, **kw) if stream
                         else self.model.complete(messages, TOOL_SCHEMAS, **kw))
            except ModelUnavailable as e:
                mark_error(span, str(e)[:200])
                raise
            set_attrs(span, gen_ai__usage__input_tokens=reply.prompt_tokens,
                      gen_ai__usage__output_tokens=reply.completion_tokens,
                      kisht__cached_tokens=reply.cached_tokens,
                      kisht__queue_wait_s=round(getattr(reply, "queue_wait_s", 0.0), 3),
                      kisht__tool_calls=[tc.name for tc in reply.tool_calls] or None)
        result.model_calls += 1
        result.prompt_tokens += reply.prompt_tokens
        result.cached_tokens += reply.cached_tokens
        result.queue_wait_s += getattr(reply, "queue_wait_s", 0.0)
        return reply

    def _follow_language(self, text: str) -> None:
        lang = detect(text, self.lender.languages.allowed)
        if lang:
            self.calls.set_state(self.call_id, language=lang)

    def _log(self, action: str, args: dict, outcome: str) -> None:
        self.guard.audit.record(call_id=self.call_id, tenant_id=self.lender.id, action=action,
                                args=args, outcome=outcome, detail=action)


def prepare(model: ChatModel, guard: PolicyGuard, borrower_id: str, channel: str = "voice") -> bool:
    """Before a call connects (while it rings): have the model server read this borrower's
    instructions and greeting, so the first reply does not wait about 5 s for that. Starts no
    contact, writes nothing; False if there is nothing to prepare."""
    warm = getattr(model, "warm", None)
    borrower = guard.ledger.borrower(borrower_id)
    if not warm or not borrower:
        return False
    lang = borrower["language"]
    if lang not in guard.lender.languages.allowed:
        lang = guard.lender.languages.default
    first_name = borrower["name"].split()[0]
    greeting = {"role": "assistant",
                "content": greeting_for(guard.lender, lang, first_name, channel)}
    messages = [*build_messages(guard.lender, [greeting], guard.today(), first_name, channel),
                {"role": "user", "content": "."}]
    threading.Thread(target=warm, args=(messages, TOOL_SCHEMAS), daemon=True).start()
    return True


def greeting_for(lender: Any, lang: str, first_name: str, channel: str) -> str:
    """The first thing the borrower hears or reads. On a phone call it also says that the
    call is recorded (RBI 2026 recovery directions, 100P), before anything else is said."""
    text = GREETING.get(lang, GREETING["en"]).format(
        agent=lender.agent_name, lender=_short(lender.name), first_name=first_name)
    if channel == "voice" and lender.contact.recording_notice:
        text = f"{text} {pack_say(lang, 'recorded')}"
    return text


def _short(name: str) -> str:
    return name.split(" (")[0].replace(" Ltd", "")
