from datetime import datetime

from kisht_support import IST, TODAY, make_account
from test_agent import FakeModel, text, tool

from kisht.agent import Agent
from kisht.planner import Planner


def accounts(ledger):
    a = make_account(ledger, borrower_id="br_1", loan_id="ln_1")               # 5 days overdue
    b = make_account(ledger, overdue=False, borrower_id="br_2", loan_id="ln_2")  # due 12 Nov
    c = make_account(ledger, dnd=True, borrower_id="br_3", loan_id="ln_3")       # overdue, DND
    return a, b, c


def test_model_decides_priority_channel_and_approach_then_code_orders_it(guard, ledger):
    accounts(ledger)
    model = FakeModel(text(
        "ln_2 | low | chat | pre-due, good history | gentle reminder of 12 Nov EMI\n"
        "ln_1 | high | voice | 5 days overdue | ask what is stopping payment\n"
        "ln_3 | medium | chat | overdue, DND number | chat reminder with payment link"))
    r = Planner(guard, model).plan(TODAY)
    assert [p.loan_id for p in r.queue] == ["ln_1", "ln_3", "ln_2"]
    assert r.queue[0].channel == "voice" and r.blocked == [] and r.unplanned == []
    assert ledger.plan_for("ln_1", TODAY)["approach"] == "ask what is stopping payment"


def test_the_guard_blocks_planner_mistakes(guard, ledger):
    accounts(ledger)
    model = FakeModel(text("ln_1 | high | voice | overdue | call\n"
                           "ln_2 | low | chat | pre-due | remind\n"
                           "ln_3 | high | voice | overdue | call"))           # DND: no calls
    r = Planner(guard, model).plan(TODAY)
    assert r.blocked == [("ln_3", "dnd")]
    assert ledger.plan_for("ln_3", TODAY)["status"] == "blocked:dnd"
    assert guard.audit.telemetry()["blocked_by_rule"] == {"dnd": 1}


def test_nothing_is_queued_outside_contact_hours(guard, ledger, clock):
    accounts(ledger)
    clock["now"] = datetime(2026, 11, 10, 7, 0, tzinfo=IST)
    model = FakeModel(text("ln_1 | high | chat | a | b\nln_2 | low | chat | a | b\n"
                           "ln_3 | low | chat | a | b"))
    r = Planner(guard, model).plan(TODAY)
    assert r.queue == [] and {c for _, c in r.blocked} == {"outside_contact_window"}


def test_garbage_and_unknown_ids_are_ignored_and_omissions_reported(guard, ledger):
    accounts(ledger)
    model = FakeModel(text("Sure! Here is the plan:\n"
                           "ln_1 | urgent | voice | x | y\n"                 # bad priority
                           "ln_9 | high | chat | not in the batch | y\n"    # unknown id
                           "- ln_2 | low | chat | pre-due | remind gently"),
                      text("still nothing useful"))                       # the one retry
    r = Planner(guard, model).plan(TODAY)
    assert [p.loan_id for p in r.queue] == ["ln_2"]
    assert sorted(r.unplanned) == ["ln_1", "ln_3"]


def test_the_planner_sees_no_names_or_phone_numbers(guard, ledger):
    accounts(ledger)
    model = FakeModel(text(""), text(""))
    Planner(guard, model).plan(TODAY)
    prompt = model.requests[0][0]["content"]
    assert "Priya" not in prompt and "+9190" not in prompt and "DND" in prompt


def test_memory_reaches_the_next_conversation_only_after_identity(guard, calls, ledger):
    a, _, _ = accounts(ledger)
    first = FakeModel(tool("verify_identity", pincode="560038"), text("Kab tak pay karenge?"),
                      text("Borrower said salary is late; will pay on 14 Nov. Follow up 15 Nov."))
    agent, _ = Agent.start(guard=guard, calls=calls, model=first, borrower_id=a[0],
                           loan_id=a[1], channel="chat")
    agent.handle("PIN 560038")
    end = agent.finish()
    assert end["outcome"] == "talked" and end["note"].startswith("Borrower said salary")
    second = FakeModel(text("Pehle PIN code batayein."), tool("verify_identity", pincode="560038"),
                       tool("get_dues"), text("Pichli baar aapne 14 Nov kaha tha."))
    agent2, _ = Agent.start(guard=guard, calls=calls, model=second, borrower_id=a[0],
                            loan_id=a[1], channel="chat")
    agent2.handle("haan")
    assert "salary is late" not in str(second.requests[0])       # nothing before identity
    agent2.handle("PIN 560038")
    dues = [m for m in calls.messages(agent2.call_id) if m["role"] == "tool"][-1]["content"]
    assert "salary is late" in dues


def test_outcome_is_decided_by_code(guard, calls, ledger):
    a, _, _ = accounts(ledger)
    model = FakeModel(tool("escalate_to_human", reason="hardship", summary="Lost job."),
                      text("I am sorry. Our team will call you."), text("Lost job; escalated."))
    agent, _ = Agent.start(guard=guard, calls=calls, model=model, borrower_id=a[0], loan_id=a[1],
                           channel="chat")
    agent.handle("I lost my job last month")
    assert agent.finish()["outcome"] == "escalated:hardship"


def test_accounts_the_model_skips_get_one_retry(guard, ledger):
    accounts(ledger)
    model = FakeModel(text("ln_1 | high | chat | overdue | ask"),          # skipped ln_2, ln_3
                      text("ln_2 | low | chat | pre-due | remind\nln_3 | medium | chat | dnd | chat"))
    r = Planner(guard, model).plan(TODAY)
    assert r.unplanned == [] and len(r.queue) == 3 and r.model_calls == 2
