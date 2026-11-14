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
    assert greeting.startswith("Namaste, main Asha bol rahi hoon, Demo Finance ki automated "
                               "assistant")     # says what it is before anything else
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
    assert t.replaced == ["false_promise_claim"] and t.reply.endswith(("Is that right?", "Sahi hai?"))


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


def test_link_claim_that_persists_is_made_true_by_code(guard, calls, account, ledger):
    model = FakeModel(tool("verify_identity", pincode="560038"),
                      text("I'll send you the payment link now."),
                      text("I have sent the link to your phone."))
    agent, _ = start(guard, calls, account, model)
    t = agent.handle("PIN 560038")
    links = ledger.payment_links(account[1])
    assert t.replaced == ["unbacked_link_claim"] and "send_payment_link" in t.tool_calls
    assert len(links) == 1                       # sent through the guard, for what is overdue
    assert t.reply == agent.say("link_sent", amount=f"{links[0]['amount']:,}")


def test_link_claim_before_identity_sends_nothing_and_asks_who_is_speaking(guard, calls, account,
                                                                          ledger):
    model = FakeModel(text("I'll send you the payment link now."),
                      text("I have sent the link to your phone."))
    agent, _ = start(guard, calls, account, model)
    t = agent.handle("ok send it")
    assert not ledger.payment_links(account[1]) and t.reply == agent.say("verify_first")


def test_confirmation_claim_without_a_saved_promise_is_replaced(guard, calls, account):
    model = FakeModel(tool("verify_identity", pincode="560038"),
                      tool("record_promise_to_pay", amount=3000, pay_date="2026-11-14"),
                      text("Rs 3000 on Saturday 14 November. Sahi hai?"),
                      text("Aapka confirmation mil gaya hai, dhanyavaad!"))
    agent, _ = start(guard, calls, account, model)
    agent.handle("PIN 560038, 14 ko 3000")
    t = agent.handle("Thank you")                      # not a clear yes
    assert t.replaced == ["false_promise_claim"] and t.reply.endswith(("Is that right?", "Sahi hai?"))


def test_identity_detail_without_the_tool_gets_one_retry(guard, calls, account):
    # Seen in the Docker test: the model said "this DOB doesn't look right" without checking.
    model = FakeModel(text("Yeh date sahi nahi lag rahi. PIN code batayein?"),
                      tool("verify_identity", date_of_birth="1990-04-02"),
                      tool("get_dues"),
                      text("Dhanyavaad Priya ji, pehchan ho gayi."))
    agent, _ = start(guard, calls, account, model)
    turn = agent.handle("Haan, 2 April 1990")
    assert turn.tool_calls == ["verify_identity", "get_dues"]
    assert calls.get(agent.call_id, "identity_verified")


def test_repeated_identical_tool_calls_stop_and_read_back(guard, calls, account):
    # Seen live in Telugu: the model re-ran the same promise + link calls until it gave up.
    promise = tool("record_promise_to_pay", amount=3000, pay_date="2026-11-11")
    model = FakeModel(tool("verify_identity", date_of_birth="1990-04-02"), tool("get_dues"),
                      text("Ok."), promise, promise)
    agent, _ = start(guard, calls, account, model)
    agent.handle("Haan main Priya, DOB 2 April 1990")
    turn = agent.handle("Kal 3000 de dungi")
    assert turn.tool_calls == ["record_promise_to_pay"] and turn.model_calls == 2
    assert "Rs 3000" in turn.reply and turn.reply.endswith(("Is that right?", "Sahi hai?"))


def test_a_blocked_closing_line_after_a_saved_promise_leaves_just_the_confirmation(
        guard, calls, account, ledger):
    # Seen in the simulated day: "noted: Rs 5350 ... Sorry, I couldn't sort that out."
    model = FakeModel(
        tool("verify_identity", pincode="560038"), tool("get_dues"), text("Kab tak?"),
        tool("record_promise_to_pay", amount=3000, pay_date="2026-11-14"), text("Sahi hai?"),
        text("Payment link bhej diya hai."), text("Payment link bhej diya hai."))
    agent, _ = start(guard, calls, account, model)
    agent.handle("Haan, PIN 560038")
    agent.handle("14 ko kar dunga")
    t = agent.handle("haan ji")
    assert t.promise_saved and "unbacked_link_claim" in t.replaced
    assert t.reply == "Dhanyavaad, note kar liya: Rs 3000 on Saturday 14 November."


# ---------- seen in the full eval: said but not done, repeating, wrong language ----------

def test_no_contact_promise_without_opt_out_is_asked_again(guard, calls, account):
    model = FakeModel(text("I understand. I will not contact you again on this channel."),
                      tool("opt_out"), text("Done, we will not contact you again."))
    agent, _ = start(guard, calls, account, model)
    result = agent.handle("Leave me alone, please.")
    assert "opt_out" in result.tool_calls
    assert result.reply == "Done, we will not contact you again."
    assert "did not call opt_out" in model.requests[1][-1]["content"]


def test_no_contact_promise_never_goes_out_unbacked(guard, calls, account):
    model = FakeModel(text("Theek hai, hum aapko dobara call nahi karenge."),
                      text("Ji, ab aapko call nahi karenge."))
    agent, _ = start(guard, calls, account, model)
    result = agent.handle("mujhe call mat karo")
    assert result.replaced == ["unbacked_optout_claim"]
    assert "nahi karenge" not in result.reply


def test_saying_the_same_thing_again_is_asked_again(guard, calls, account):
    same = ("Priya ji, 200 rupaye se aapka EMI cover nahi hoga. Agar aap 750 rupaye aaj ya kal "
            "bhej sakti hain, toh hum aapki baat accept kar sakte hain.")
    model = FakeModel(text(same), text(same.replace("Priya ji", "Priya ji, main samajhti hoon,")),
                      tool("escalate_to_human", reason="hardship", summary="cannot pay minimum"),
                      text("Main aapki baat hamari team ko de rahi hoon."))
    agent, _ = start(guard, calls, account, model)
    agent.handle("mere paas sirf 200 hain")
    result = agent.handle("750 nahi ho payega, bas 200")
    assert "escalate_to_human" in result.tool_calls
    assert "already said almost exactly this" in model.requests[2][-1]["content"]


def test_model_is_told_the_borrowers_language(guard, calls, account):
    model = FakeModel(text("Could you share your date of birth or PIN code?"))
    agent, _ = start(guard, calls, account, model)
    agent.handle("Yes this is me, what is this call about please?")
    sent = model.requests[0]
    assert "Reply in English." in sent[-2]["content"]       # before the borrower's words ...
    assert sent[-1]["content"].startswith("Yes this is me")  # ... which stay last


def test_a_named_day_with_no_promise_recorded_is_asked_again(guard, calls, account):
    model = FakeModel(tool("verify_identity", pincode="560038"), text("Dhanyavaad Priya ji."),
                      text("Achha, 14 November ko payment ka plan sun kar khushi hui."),
                      tool("record_promise_to_pay", amount=3000, pay_date="2026-11-14"),
                      text("ok"))
    agent, _ = start(guard, calls, account, model)
    agent.handle("PIN 560038")
    result = agent.handle("main 14 November ko pura EMI de dungi")
    assert "record_promise_to_pay" in result.tool_calls
    assert "The borrower named a day" in model.requests[3][-1]["content"]


def test_notes_for_agreement_questions_and_hardship(guard, calls, account):
    model = FakeModel(text("Ji?"), text("Ji?"))
    agent, _ = start(guard, calls, account, model)
    agent.handle("is loan par late fee kitni lagti hai?")
    assert "call lookup_agreement now" in model.requests[0][-1]["content"]
    agent.handle("meri naukri chali gayi hai, paise nahi hain")
    assert "escalate_to_human with reason hardship" in model.requests[1][-1]["content"]
    assert "lookup_agreement now" not in model.requests[1][-1]["content"]


def test_promise_saved_said_again_later_is_not_blocked(guard, calls, account):
    model = FakeModel(text("Aapka vaada record ho gaya hai, dhanyavaad."))
    agent, _ = start(guard, calls, account, model)
    calls.set_state(agent.call_id, did_save_promise=True)
    assert agent.handle("theek hai, thanks").replaced == []


def test_hand_over_said_without_the_tool_is_asked_again(guard, calls, account):
    model = FakeModel(text("Priya ji, main aapki baat ko team ko forward kar rahi hoon."),
                      tool("escalate_to_human", reason="hardship", summary="job loss"),
                      text("Hamari team aapko call karegi."))
    agent, _ = start(guard, calls, account, model)
    result = agent.handle("naukri chali gayi, kuch nahi de sakti")
    assert "escalate_to_human" in result.tool_calls
    assert "did not call escalate_to_human" in model.requests[1][-1]["content"]


def test_hand_over_claim_is_made_true_by_code(guard, calls, account, ledger):
    model = FakeModel(text("I have forwarded this to our team."),
                      text("Our team will call you soon."))
    agent, _ = start(guard, calls, account, model)
    result = agent.handle("I do not agree with this amount at all.")
    assert result.replaced == ["unbacked_handoff_claim"]
    assert result.ended == "escalate_to_human" and result.reply == agent.say("team_will_call")
    case = ledger.escalations(account[1])
    assert len(case) == 1 and case[0]["reason"] == "callback"
    assert "do not agree" in case[0]["summary"]


def test_a_yes_to_the_offered_team_call_opens_a_case_without_the_model(guard, calls, account,
                                                                       ledger):
    model = FakeModel(text("Sure, I have waived your late fee."))     # blocked: only an offer
    agent, _ = start(guard, calls, account, model)
    guard.verify_identity(agent.call_id, pincode="560038")
    offer = agent.handle("Please remove the late fee.")
    assert offer.reply == agent.say("cannot_decide") and not ledger.escalations(account[1])
    agent.model = FakeModel()                                          # never asked
    result = agent.handle("Yes")
    assert result.ended == "escalate_to_human" and result.reply == agent.say("team_will_call")
    assert len(ledger.escalations(account[1])) == 1


def test_anything_but_a_clear_yes_to_the_offer_goes_to_the_model_with_a_note(guard, calls,
                                                                            account):
    agent, _ = start(guard, calls, account, FakeModel(text("I have waived your late fee.")))
    guard.verify_identity(agent.call_id, pincode="560038")
    agent.handle("Please remove the late fee.")
    agent.model = FakeModel(text("Okay."))
    agent.handle("what would the team do?")
    assert "If the borrower accepts, call escalate_to_human now" in \
        agent.model.requests[0][-1]["content"]


def test_the_offer_is_made_once_then_code_hands_over(guard, calls, account, ledger):
    waived = text("I have waived your late fee.")
    agent, _ = start(guard, calls, account, FakeModel(waived, waived))
    guard.verify_identity(agent.call_id, pincode="560038")
    first = agent.handle("Please remove the late fee.")
    second = agent.handle("but why not, just remove it")
    assert first.reply == agent.say("cannot_decide")
    assert second.reply == agent.say("team_will_call") and second.ended == "escalate_to_human"
    assert len(ledger.escalations(account[1])) == 1


def test_hardship_handed_over_by_code_goes_to_the_hardship_team(guard, calls, account, ledger):
    model = FakeModel(text("I am forwarding this to our team."), text("Our team will call you."))
    agent, _ = start(guard, calls, account, model)
    agent.handle("I lost my job last month, I cannot pay.")
    assert ledger.escalations(account[1])[0]["reason"] == "hardship"


def test_an_offer_to_hand_over_is_not_a_claim():
    from kisht.confirm import claims_handed_over
    assert not claims_handed_over("I can pass it to our team. Shall I do that?")
    assert not claims_handed_over("Kya main team se aapko call karwaun?")
    assert claims_handed_over("Team aapko jald hi call karegi.")
    assert claims_handed_over("I'll escalate this to my supervisor right away.")


class ForcingModel(FakeModel):
    """A model server that accepts a forced tool (tool_choice)."""
    force_tools = True

    def __init__(self, *replies):
        super().__init__(*replies)
        self.forced = []

    def complete(self, messages, tools=None, tool_choice=None):
        self.forced.append(tool_choice)
        return super().complete(messages, tools)


def test_the_second_try_names_the_tool_where_the_server_allows_it(guard, calls, account, ledger):
    model = ForcingModel(text("I have sent the link to your phone."),
                         tool("send_payment_link", amount=3000), text("Link sent for Rs 3000."))
    agent, _ = start(guard, calls, account, model)
    guard.verify_identity(agent.call_id, pincode="560038")
    result = agent.handle("please send me the link")
    assert model.forced == [None, "send_payment_link", None]
    assert result.replaced == [] and len(ledger.payment_links(account[1])) == 1


def test_a_server_that_does_not_say_so_is_never_sent_a_forced_tool(guard, calls, account):
    model = FakeModel(text("I have sent the link to your phone."),      # complete() takes no
                      tool("send_payment_link", amount=3000), text("Done."))   # tool_choice
    agent, _ = start(guard, calls, account, model)
    guard.verify_identity(agent.call_id, pincode="560038")
    assert "send_payment_link" in agent.handle("please send me the link").tool_calls


def test_a_payment_the_agent_cannot_see_is_answered_plainly_not_with_a_team_call(guard, calls,
                                                                                account, ledger):
    said = text("Great, your payment has been received and your account is clear!")
    agent, _ = start(guard, calls, account, FakeModel(said, said))
    guard.verify_identity(agent.call_id, pincode="560038")
    first = agent.handle("I have paid just now through the link.")
    second = agent.handle("so it is done, right?")
    assert first.replaced == ["false_claim"] and first.reply == agent.say("payment_pending")
    assert second.reply == agent.say("payment_pending") and second.ended is None
    assert not ledger.escalations(account[1])


# ---------- found in the full run after D114 ----------

def test_a_link_claim_after_the_borrower_named_a_day_asks_for_the_promise(guard, calls, account,
                                                                         ledger):
    model = FakeModel(text("I am sending the link for the 14th."),
                      text("I have sent the link to your phone."))
    agent, _ = start(guard, calls, account, model)
    guard.verify_identity(agent.call_id, pincode="560038")
    t = agent.handle("I will pay on 14 November")
    assert not ledger.payment_links(account[1])
    assert t.reply == agent.say("promise_ask") and t.ended is None


def test_a_false_promise_claim_asks_for_the_date_before_offering_the_team(guard, calls, account):
    said = text("Your promise has been recorded.")
    agent, _ = start(guard, calls, account, FakeModel(said, said, said, said, said, said))
    guard.verify_identity(agent.call_id, pincode="560038")
    replies = [agent.handle("ok").reply for _ in range(3)]
    assert replies == [agent.say("promise_ask"), agent.say("stuck"), agent.say("team_will_call")]


def test_hardship_goes_to_the_team_after_two_replies_without_a_hand_over(guard, calls, account,
                                                                        ledger):
    chat = [text(f"I understand, that is hard. Answer {i}.") for i in range(6)]
    agent, _ = start(guard, calls, account, FakeModel(*chat))
    guard.verify_identity(agent.call_id, pincode="560038")
    agent.handle("I lost my job last month, I cannot pay")
    agent.handle("what can be done?")
    assert not ledger.escalations(account[1])
    t = agent.handle("please help")
    assert t.reply == agent.say("team_will_call") and t.ended == "escalate_to_human"
    assert [e["reason"] for e in ledger.escalations(account[1])] == ["hardship"]


def test_a_link_claim_to_a_borrower_in_hardship_hands_over_instead(guard, calls, account, ledger):
    model = FakeModel(text("I'll send you the payment link now."),
                      text("I have sent the link to your phone."))
    agent, _ = start(guard, calls, account, model)
    guard.verify_identity(agent.call_id, pincode="560038")
    t = agent.handle("My mother is in hospital, I have no money")
    assert not ledger.payment_links(account[1]) and t.reply == agent.say("team_will_call")
