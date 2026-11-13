"""The rules-to-code table (compliance/rbi-recovery-2027.yaml) must stay true: every row
marked enforced points at a guard and tests that exist, and the published page matches the
file. Plus the tests for the gaps the 2026 RBI recovery directions exposed."""
from pathlib import Path

import pytest
from test_agent import FakeModel, text, tool

from kisht import compliance
from kisht.agent import Agent, greeting_for
from kisht.guard import GuardRefused
from kisht.languages import PACKS, say


def test_every_rule_points_at_code_and_tests_that_exist():
    book = compliance.load()
    assert compliance.problems(book) == []
    s = compliance.summary(book)
    assert s["enforced"] >= 6 and s.get("gap", 0) >= 1          # honest: gaps are listed too


def test_a_broken_reference_is_reported():
    book = compliance.load()
    book.rules[0].tests.append("tests/test_guard.py::test_that_was_deleted")
    book.rules[0].guard.append("kisht.guard:PolicyGuard.no_such_method")
    book.rules[0].codes.append("no_such_code")
    found = compliance.problems(book)
    assert len(found) == 3 and all(p.startswith(book.rules[0].id) for p in found)


def test_published_page_matches_the_file():
    page = Path("docs/COMPLIANCE.md").read_text(encoding="utf-8")
    assert page == compliance.render_markdown(compliance.load()), \
        "run `uv run kisht compliance --write`"


def test_no_agent_contact_while_the_desk_has_a_hardship_case(guard, calls, account, ledger):
    """RBI 2026 recovery directions 100Y(6): bereavement, medical emergencies and the like
    are occasions to avoid. Once the borrower has told us, the agent stays away until a
    person has dealt with it."""
    model = FakeModel(tool("escalate_to_human", reason="bereavement",
                           summary="Father passed away last week"), text("Hum samajhte hain."))
    agent, _ = Agent.start(guard=guard, calls=calls, model=model, borrower_id=account[0],
                           loan_id=account[1], channel="chat")
    agent.handle("mere pitaji ka dehant ho gaya hai")
    with pytest.raises(GuardRefused) as e:
        guard.check_contact(account[0], "chat")
    assert e.value.code == "with_human_desk"
    case = ledger.escalations(account[1])[0]
    ledger.db.execute("UPDATE escalations SET status='resolved' WHERE id=?", (case["id"],))
    guard.check_contact(account[0], "chat")                    # resolved: contact may resume

    other = FakeModel(tool("escalate_to_human", reason="wrong_person", summary="Not the borrower"),
                      text("Dhanyavaad."))
    again, _ = Agent.start(guard=guard, calls=calls, model=other, borrower_id=account[0],
                           loan_id=account[1], channel="chat")
    again.handle("main Priya nahi hoon")
    try:
        guard.check_contact(account[0], "chat")                # wrong person is not a hold
    except GuardRefused as refused:
        assert refused.code != "with_human_desk"


def test_a_phone_call_starts_by_saying_it_is_recorded(guard, calls, account):
    """100P: tell the borrower the conversation is recorded. Code writes the greeting."""
    for lang in PACKS:
        voice = greeting_for(guard.lender, lang, "Priya", "voice")
        assert voice.endswith(say(lang, "recorded")) and "Priya" in voice
        assert say(lang, "recorded") not in greeting_for(guard.lender, lang, "Priya", "chat")
    _, greeting = Agent.start(guard=guard, calls=calls, model=FakeModel(),
                              borrower_id=account[0], loan_id=account[1], channel="voice")
    assert say("hi", "recorded") in greeting
    assert calls.messages(calls.r.keys("call:*:state")[0].split(":")[1])[0]["content"] == greeting


def test_written_messages_and_complaint_answers_carry_the_grievance_officer(guard, calls,
                                                                              account):
    """100AA: every recovery communication carries the grievance officer's name, email,
    telephone number and address."""
    from kisht.knowledge import Agreement
    from kisht.tools import ToolRunner

    officer = guard.lender.grievance_officer
    call_id = calls.start_call("demo-nbfc", "hi")
    guard.start_contact(call_id, borrower_id=account[0], loan_id=account[1], channel="chat")
    guard.verify_identity(call_id, date_of_birth="1990-04-02")
    sent = guard.send_payment_link(call_id, amount=3000)
    for part in (officer.name, officer.email, officer.phone, officer.address):
        assert part in sent["message_text"]
    runner = ToolRunner(guard, Agreement.load("knowledge/demo-nbfc.yaml"))
    answer = runner.run(call_id, "lookup_agreement", '{"question": "how do I complain? grievance"}')
    assert officer.email in answer.content["grievance_officer"]
    assert "Ombudsman" in str(answer.content["sections"])
    other = runner.run(call_id, "lookup_agreement", '{"question": "late fee charges"}')
    assert "grievance_officer" not in other.content
