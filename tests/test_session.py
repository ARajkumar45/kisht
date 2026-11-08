"""Whole caller turns with a scripted fake model (no real model needed)."""
import json

import pytest

from receptionist.model_client import ModelReply, ModelUnavailable, ToolCall
from receptionist.session import MAX_TOOL_ROUNDS, CallSession

DETAILS = {"service_id": "haircut-men", "start": "2026-11-10T11:00",
           "customer_name": "Priya", "customer_phone": "9845012345"}
READ_BACK = "Men's haircut with Ravi on Tuesday 10 November at 11:00 AM, for Priya, phone ending 2345"


class FakeModel:
    """Returns the scripted replies in order and keeps every request it received."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def complete(self, messages, tools):
        self.requests.append(json.loads(json.dumps(messages)))
        if not self.replies:
            raise AssertionError("the model was called more often than the script allows")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def text(content):
    return ModelReply(content=content)


def tool(name, **args):
    return ModelReply(content="", tool_calls=[ToolCall(f"t_{name}_{len(args)}", name,
                                                       json.dumps(args))])


def start(guard, salon, model, language=None):
    return CallSession.start(salon, guard.calls, guard, model, language=language)


def test_greeting_is_said_and_saved(guard, salon):
    session, greeting = start(guard, salon, FakeModel(), language="hi")
    assert greeting.startswith("Namaste, Glow Salon")
    assert guard.calls.messages(session.call_id) == [{"role": "assistant", "content": greeting}]


def test_simple_question_one_model_call(guard, salon):
    model = FakeModel(text("We're open 10 to 8 on weekdays."))
    session, _ = start(guard, salon, model)
    turn = session.handle("What are your timings?")
    assert turn.reply == "We're open 10 to 8 on weekdays."
    assert turn.model_calls == 1 and not turn.tool_calls
    sent = model.requests[0]
    assert sent[0]["role"] == "system" and "Glow Salon" in sent[0]["content"]
    assert sent[-1] == {"role": "user", "content": "What are your timings?"}


# ---------- booking: the model proposes, the caller's yes books (D43, D44) ----------

def test_full_booking_is_finished_by_code_on_the_callers_yes(guard, salon):
    model = FakeModel(tool("book_visit", **DETAILS), text(READ_BACK + ". Shall I book it?"))
    session, _ = start(guard, salon, model)
    first = session.handle("Haircut kal 11 baje, Priya, 9845012345")
    assert not first.booked and "Shall I book it?" in first.reply
    second = session.handle("haan, book kar do")
    assert second.booked and second.model_calls == 0           # no model call at all
    assert second.reply == f"Ho gaya, book kar diya: {READ_BACK}. Milte hain!"
    assert guard.calls.get(session.call_id, "pending_booking") is None
    assert guard.bookings.get(guard.calls.get(session.call_id, "booking_id")).staff_id == "ravi"
    actions = [e["action"] for e in guard.audit.for_call(session.call_id)]
    assert actions == ["propose_booking", "caller_yes", "confirm_booking"]
    assert model.replies == []                                   # script fully used


def test_without_a_yes_nothing_is_booked(guard, salon):
    model = FakeModel(tool("book_visit", **DETAILS), text(READ_BACK + ". Shall I book it?"),
                      text("A men's haircut is Rs 300."))
    session, _ = start(guard, salon, model)
    session.handle("Haircut tomorrow 11, Priya, 9845012345")
    turn = session.handle("hmm, how much does it cost?")
    assert not turn.booked and turn.reply == "A men's haircut is Rs 300."
    assert guard.calls.get(session.call_id, "pending_booking") is not None   # still waiting
    assert guard.calls.get(session.call_id, "booking_id") is None


def test_model_claiming_a_booking_is_replaced_with_the_read_back(guard, salon):
    model = FakeModel(tool("book_visit", **DETAILS), text("Great, I've booked it!"))
    session, _ = start(guard, salon, model)
    turn = session.handle("Haircut tomorrow 11, Priya, 9845012345")
    assert not turn.booked and turn.replaced_false_claim
    assert turn.reply == f"Before I book it, let me confirm: {READ_BACK}. Shall I book it?"
    assert guard.calls.get(session.call_id, "booking_id") is None


def test_claim_without_any_tool_call_is_replaced(guard, salon):
    session, _ = start(guard, salon, FakeModel(text("Booked! See you tomorrow.")))
    turn = session.handle("book me a haircut")
    assert turn.replaced_false_claim
    assert turn.reply == "Nothing is booked yet. Which service and what time would you like?"


def test_after_a_real_booking_the_model_may_say_so(guard, salon):
    model = FakeModel(tool("book_visit", **DETAILS), text(READ_BACK + ". Shall I book it?"),
                      text("Yes, you're booked for Tuesday at 11."))
    session, _ = start(guard, salon, model)
    session.handle("Haircut tomorrow 11, Priya, 9845012345")
    session.handle("yes")
    turn = session.handle("so am I booked?")
    assert turn.reply == "Yes, you're booked for Tuesday at 11." and not turn.replaced_false_claim


def test_yes_when_the_slot_was_just_taken(guard, salon):
    other = guard.calls.start_call("glow-salon", "en")
    guard.propose_booking(other, **{**DETAILS, "customer_name": "Arun",
                                     "customer_phone": "9845000000"})
    guard.mark_caller_yes(other)
    model = FakeModel(tool("book_visit", **DETAILS), text(READ_BACK + ". Shall I book it?"))
    session, _ = start(guard, salon, model)
    session.handle("Haircut tomorrow 11, Priya, 9845012345")
    guard.confirm_booking(other, pending_id=guard.calls.get(other, "pending_booking")["id"])
    turn = session.handle("yes please")
    assert not turn.booked
    assert turn.reply == "Sorry, that time was just taken. Shall I look for another time?"


def test_hindi_caller_gets_hindi_fixed_lines(guard, salon):
    session, _ = start(guard, salon, FakeModel(text("Booking ho gayi!")))
    turn = session.handle("mujhe kal haircut chahiye")
    assert turn.reply.startswith("Abhi tak kuch book nahi hua hai")


# ---------- model misbehaviour ----------

def test_too_many_tool_rounds_ends_politely(guard, salon):
    loops = [tool("check_availability", service_id="haircut-men", day="2026-11-10")
             for _ in range(MAX_TOOL_ROUNDS)]
    session, _ = start(guard, salon, FakeModel(*loops))
    turn = session.handle("any slot?")
    assert turn.reply.startswith("Sorry, I couldn't sort that out")
    assert guard.calls.get(session.call_id, "stuck_count") == 1


def test_model_down_gives_fallback_and_flags_handoff(guard, salon):
    session, _ = start(guard, salon, FakeModel(ModelUnavailable("connection refused")))
    turn = session.handle("hello?")
    assert turn.fallback and "pass your message to the owner" in turn.reply
    assert guard.calls.get(session.call_id, "handoff_needed") is True


def test_notebook_holds_whole_conversation_in_order(guard, salon):
    model = FakeModel(tool("check_availability", service_id="haircut-men", day="2026-11-10"),
                      text("10 AM is free."))
    session, _ = start(guard, salon, model)
    session.handle("slots tomorrow?")
    roles = [m["role"] for m in guard.calls.messages(session.call_id)]
    assert roles == ["assistant", "user", "assistant", "tool", "assistant"]


@pytest.mark.parametrize("bad", ["", "   "])
def test_empty_model_reply_counts_as_stuck(guard, salon, bad):
    session, _ = start(guard, salon, FakeModel(text(bad)))
    assert session.handle("hello").reply.startswith("Sorry")


def test_let_me_check_without_a_tool_is_retried_once(guard, salon):
    model = FakeModel(text("Let me check the availability for tomorrow."),
                      tool("check_availability", service_id="haircut-men", day="2026-11-10"),
                      text("10 AM is free."))
    session, _ = start(guard, salon, model)
    turn = session.handle("haircut slot tomorrow?")
    assert turn.reply == "10 AM is free."
    assert turn.tool_calls == ["check_availability"] and turn.model_calls == 3
    assert "Let me check" not in json.dumps(guard.calls.messages(session.call_id))
    assert any(e["action"] == "stall_retry" for e in guard.audit.for_call(session.call_id))


def test_stall_is_retried_only_once(guard, salon):
    model = FakeModel(text("Let me check."), text("One moment please."))
    session, _ = start(guard, salon, model)
    assert session.handle("slot?").reply == "One moment please."
    assert len(model.replies) == 0


def test_unchecked_availability_is_retried_with_a_note_that_is_not_saved(guard, salon):
    model = FakeModel(text("Haan, facial parso shaam ko ho sakta hai."),
                      tool("check_availability", service_id="facial", day="2026-11-11"),
                      text("Parso 10 baje se slots free hain."))
    session, _ = start(guard, salon, model)
    turn = session.handle("Parso shaam ko facial ho sakta hai?")
    assert turn.tool_calls == ["check_availability"]
    assert turn.reply == "Parso 10 baje se slots free hain."
    assert "System note" in json.dumps(model.requests[1])        # nudge sent once...
    assert "System note" not in json.dumps(model.requests[2])    # ...not afterwards
    assert "System note" not in json.dumps(guard.calls.messages(session.call_id))
    assert "parso shaam ko ho sakta" not in json.dumps(guard.calls.messages(session.call_id))


def test_availability_still_unchecked_after_retry_is_replaced(guard, salon):
    model = FakeModel(text("Yes, 11 AM is free tomorrow."),
                      text("Yes, 11 AM is free tomorrow."))
    session, _ = start(guard, salon, model)
    turn = session.handle("Is 11 free tomorrow?")
    assert turn.replaced_unchecked_claim
    assert turn.reply.startswith("I'll check the schedule for you.")
    actions = [e["action"] for e in guard.audit.for_call(session.call_id)]
    assert actions == ["unchecked_availability_retry", "availability_claim_blocked"]


def test_availability_after_a_check_is_allowed(guard, salon):
    model = FakeModel(tool("check_availability", service_id="manicure", day="2026-11-14"),
                      text("Yes, Saturday 9 AM is free with Meena."))
    session, _ = start(guard, salon, model)
    turn = session.handle("Any manicure slot on Saturday?")
    assert turn.reply == "Yes, Saturday 9 AM is free with Meena."
    assert turn.model_calls == 2 and not turn.replaced_unchecked_claim
