"""Whole borrower turns with a scripted fake model (no real model needed)."""
import json
from datetime import datetime

import pytest
from kisht_support import IST, make_account

from kisht.agent import MAX_TOOL_ROUNDS, Agent
from kisht.guard import GuardRefused
from kisht.ports import ModelReply, ModelUnavailable, ToolCall
from kisht.prompt import stable_prefix


class FakeModel:
    name = "fake"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def complete(self, messages, tools=None):
        self.requests.append(json.loads(json.dumps(messages)))
        if not self.replies:
            raise AssertionError("the model was called more often than the script allows")
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def text(content):
    return ModelReply(content=content)


def tool(name, **args):
    return ModelReply(content="", tool_calls=[ToolCall(f"t_{name}", name, json.dumps(args))])


def start(guard, calls, account, model, channel="chat"):
    return Agent.start(guard=guard, calls=calls, model=model, borrower_id=account[0],
                       loan_id=account[1], channel=channel)


def test_greeting_names_the_borrower_and_reveals_nothing(guard, calls, account):
    _, greeting = start(guard, calls, account, FakeModel())
    assert greeting.startswith("Namaste, main Asha bol rahi hoon Demo Finance se")
    assert "Priya ji" in greeting and "3000" not in greeting and "EMI" not in greeting


def test_contact_rules_apply_before_a_conversation_starts(guard, calls, account, clock):
    clock["now"] = datetime(2026, 11, 10, 20, 0, tzinfo=IST)
    with pytest.raises(GuardRefused, match="contact only between"):
        start(guard, calls, account, FakeModel())


def test_no_amounts_in_the_prompt_before_identity(guard, calls, account):
    model = FakeModel(text("Kripya apni date of birth ya PIN code batayein."))
    agent, _ = start(guard, calls, account, model)
    agent.handle("haan main Priya hoon")
    system = model.requests[0][0]["content"]
    assert "3000" not in system and "overdue" not in system.lower().split("this conversation")[1]


def test_the_model_plans_several_steps_in_one_turn(guard, calls, account):
    model = FakeModel(tool("verify_identity", date_of_birth="1990-04-02"),
                      tool("get_dues"),
                      text("Dhanyavaad Priya ji. Aapki 5 November ki EMI Rs 3000 baaki hai. "
                           "Kya aaj pay kar payenge?"))
    agent, _ = start(guard, calls, account, model)
    turn = agent.handle("Haan main Priya, DOB 2 April 1990")
    assert turn.tool_calls == ["verify_identity", "get_dues"] and turn.model_calls == 3
    assert "Rs 3000" in turn.reply and turn.replaced == []


def test_full_promise_flow_saved_by_code_then_the_agent_follows_up(guard, calls, account, ledger):
    model = FakeModel(
        tool("verify_identity", pincode="560038"), tool("get_dues"),
        text("Aapki EMI Rs 3000 baaki hai. Kab tak kar payenge?"),
        tool("record_promise_to_pay", amount=3000, pay_date="2026-11-14"),
        text("Toh aap Rs 3000 on Saturday 14 November pay karenge. Sahi hai?"),
        tool("schedule_followup", on_date="2026-11-15", reason="check promise of 14 Nov"),
        text("Main 15 November ko check karungi. Aapka din shubh ho!"))
    agent, _ = start(guard, calls, account, model)
    agent.handle("Haan, PIN 560038")
    t2 = agent.handle("Salary 14 ko aayegi, tab kar dunga")
    assert t2.tool_calls == ["record_promise_to_pay"] and not t2.promise_saved
    assert ledger.open_promises(account[1]) == []
    t3 = agent.handle("haan ji")
    assert t3.promise_saved and t3.reply.startswith("Dhanyavaad, note kar liya: Rs 3000 on Saturday")
    assert t3.tool_calls == ["schedule_followup"]
    assert len(ledger.open_promises(account[1])) == 1 and ledger.followups(account[1])


def test_a_yes_that_changes_the_date_is_not_a_yes(guard, calls, account, ledger):
    model = FakeModel(tool("verify_identity", pincode="560038"),
                      tool("record_promise_to_pay", amount=3000, pay_date="2026-11-14"),
                      text("Rs 3000 on Saturday 14 November. Sahi hai?"),
                      tool("record_promise_to_pay", amount=3000, pay_date="2026-11-15"),
                      text("Rs 3000 on Sunday 15 November. Sahi hai?"))
    agent, _ = start(guard, calls, account, model)
    agent.handle("PIN 560038, 14 ko 3000 de dunga")
    t = agent.handle("haan, lekin 15 tareekh ko")
    assert not t.promise_saved and ledger.open_promises(account[1]) == []


def test_guard_refusal_reaches_the_model_and_it_adapts(guard, calls, account):
    model = FakeModel(tool("verify_identity", pincode="560038"),
                      tool("record_promise_to_pay", amount=3000, pay_date="2026-11-30"),
                      text("Sorry, the latest date I can note is 17 November. Would that work?"))
    agent, _ = start(guard, calls, account, model)
    t = agent.handle("PIN 560038. I will pay on 30 November")
    assert t.refused == ["date_out_of_policy"] and "17 November" in t.reply
    tool_msg = [m for m in calls.messages(agent.call_id) if m["role"] == "tool"][-1]
    assert json.loads(tool_msg["content"])["refused"] == "date_out_of_policy"


@pytest.mark.parametrize("bad,why", [
    ("Your EMI of Rs 3000 is overdue, Priya.", "leak_before_identity"),
    ("Priya ji, aapka loan thoda peeche hai, isliye baat karni hai.", "leak_before_identity"),
    ("Your payment is pending since last week.", "leak_before_identity"),
    ("Pay today or we will send the police.", "banned_phrase"),
])
def test_unsafe_replies_are_replaced_before_anyone_sees_them(guard, calls, account, bad, why):
    agent, _ = start(guard, calls, account, FakeModel(text(bad)))
    t = agent.handle("Haan boliye")
    assert t.replaced == [why] and t.reply != bad
    assert calls.messages(agent.call_id)[-1]["content"] == t.reply      # transcript = what was said


def test_claims_only_code_can_make_are_replaced(guard, calls, account):
    model = FakeModel(tool("verify_identity", pincode="560038"),
                      text("Done, I have waived the late fee for you."),
                      text("I cannot waive the late fee, but I can ask the team."))
    agent, _ = start(guard, calls, account, model)
    assert agent.handle("PIN 560038, please remove the late fee").replaced == ["false_claim"]
    assert agent.handle("ok").replaced == []


def test_false_promise_claim_becomes_the_read_back(guard, calls, account):
    model = FakeModel(tool("verify_identity", pincode="560038"),
                      tool("record_promise_to_pay", amount=3000, pay_date="2026-11-14"),
                      text("Great, I have recorded your promise!"))
    agent, _ = start(guard, calls, account, model)
    t = agent.handle("PIN 560038, 14 ko 3000")
    assert t.replaced == ["false_promise_claim"] and t.reply.endswith("Is that right?")


def test_escalation_ends_the_conversation(guard, calls, account, ledger):
    model = FakeModel(tool("escalate_to_human", reason="wrong_person",
                           summary="Number belongs to someone else."),
                      text("Sorry for the trouble. Thank you, goodbye."))
    agent, _ = start(guard, calls, account, model)
    t = agent.handle("Wrong number, there is no Priya here")
    assert t.ended == "escalate_to_human" and ledger.escalations(account[1])


def test_let_me_check_without_a_tool_is_retried_once(guard, calls, account):
    model = FakeModel(text("Let me check your account."),
                      tool("verify_identity", pincode="560038"), tool("get_dues"),
                      text("Rs 3000 is pending from 5 November."))
    agent, _ = start(guard, calls, account, model)
    t = agent.handle("PIN 560038, how much do I owe?")
    assert t.tool_calls == ["verify_identity", "get_dues"] and "Rs 3000" in t.reply


def test_model_down_gives_a_fallback(guard, calls, account):
    agent, _ = start(guard, calls, account, FakeModel(ModelUnavailable("down")))
    t = agent.handle("hello")
    assert t.fallback and "team" in t.reply.lower()


def test_endless_tool_loops_stop(guard, calls, account):
    loops = [tool("verify_identity", pincode="000000")] * MAX_TOOL_ROUNDS
    agent, _ = start(guard, calls, account, FakeModel(*loops))
    t = agent.handle("PIN?")
    assert t.reply.startswith("Maaf kijiye, main yeh nahi kar paayi")


def test_prompt_prefix_is_identical_across_conversations(guard, calls, ledger, lender):
    """Prefix caching (D74) needs byte-identical system text up to the per-call part."""
    a = make_account(ledger, borrower_id="br_a", loan_id="ln_a")
    m1, m2 = FakeModel(text("ok")), FakeModel(text("ok"))
    ag1, _ = start(guard, calls, make_account(ledger, borrower_id="br_b", loan_id="ln_b"), m1)
    ag2, _ = start(guard, calls, a, m2)
    ag1.handle("hi")
    ag2.handle("hi")
    prefix = stable_prefix(lender)
    assert m1.requests[0][0]["content"].startswith(prefix)
    assert m2.requests[0][0]["content"].startswith(prefix)


def test_english_speaker_switches_the_fixed_lines(guard, calls, account):
    agent, _ = start(guard, calls, account, FakeModel(ModelUnavailable("down")))
    t = agent.handle("Sorry, who is this calling please?")
    assert t.reply.startswith("Sorry, I'm having a technical problem")


@pytest.mark.parametrize("stall", ["Main aapke loan ki details check kar rahi hoon...",
                                   "Ek minute, main dekh rahi hoon"])
def test_hindi_stalls_are_retried(guard, calls, account, stall):
    model = FakeModel(text(stall), tool("verify_identity", pincode="560038"),
                      text("Dhanyavaad, verify ho gaya."))
    agent, _ = start(guard, calls, account, model)
    assert agent.handle("PIN 560038").tool_calls == ["verify_identity"]


def test_link_claim_without_the_tool_makes_the_model_act(guard, calls, account, ledger):
    model = FakeModel(tool("verify_identity", pincode="560038"),
                      text("Main aapko abhi payment link bhej rahi hoon."),
                      tool("send_payment_link", amount=3000),
                      text("Link bhej diya hai, Rs 3000 ka."))
    agent, _ = start(guard, calls, account, model)
    t = agent.handle("PIN 560038, link bhej do 3000 ka")
    assert t.tool_calls == ["verify_identity", "send_payment_link"] and t.replaced == []
    assert ledger.payment_links(account[1])


def test_link_claim_that_persists_is_replaced(guard, calls, account, ledger):
    model = FakeModel(tool("verify_identity", pincode="560038"),
                      text("I'll send you the payment link now."),
                      text("I have sent the link to your phone."))
    agent, _ = start(guard, calls, account, model)
    t = agent.handle("PIN 560038")
    assert t.replaced == ["unbacked_link_claim"] and not ledger.payment_links(account[1])


def test_confirmation_claim_without_a_saved_promise_is_replaced(guard, calls, account):
    model = FakeModel(tool("verify_identity", pincode="560038"),
                      tool("record_promise_to_pay", amount=3000, pay_date="2026-11-14"),
                      text("Rs 3000 on Saturday 14 November. Sahi hai?"),
                      text("Aapka confirmation mil gaya hai, dhanyavaad!"))
    agent, _ = start(guard, calls, account, model)
    agent.handle("PIN 560038, 14 ko 3000")
    t = agent.handle("Thank you")                      # not a clear yes
    assert t.replaced == ["false_promise_claim"] and t.reply.endswith("Is that right?")
