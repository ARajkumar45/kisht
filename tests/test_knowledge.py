import pytest
from test_agent import FakeModel, start, text, tool

from kisht.agent import Agent
from kisht.knowledge import Agreement, tokens
from kisht.tools import ToolRunner

AGREEMENT = Agreement.load("knowledge/demo-nbfc.yaml")

# A small retrieval test set: question -> the section that must come first.
QUESTIONS = [
    ("late fee kitna lagega", "4"),
    ("What is the penalty if NACH bounces?", "4"),
    ("will this affect my CIBIL score", "8"),
    ("complaint kahan karun", "10"),
    ("can I close my loan early", "6"),
    ("foreclosure charge for two wheeler", "6"),
    ("salary 10 tareekh ko aati hai, EMI date badal sakte hain?", "7"),
    ("meri naukri chali gayi", "12"),
    ("agent ne OTP maanga", "3"),
    ("can I pay half now", "5"),
    ("can your agent call my office", "9"),
    ("is this call recorded", "11"),
]


@pytest.mark.parametrize("question,section", QUESTIONS)
def test_retrieval_puts_the_right_section_first(question, section):
    assert AGREEMENT.search(question)[0].id == section


def test_unrelated_questions_find_nothing():
    assert AGREEMENT.search("what is the weather in Delhi today") == []


def test_hinglish_words_map_to_the_same_terms():
    assert tokens("jurmana") == tokens("penalty") == ["late"]


def test_lookup_needs_no_identity_and_is_audited(guard, call):
    r = ToolRunner(guard, AGREEMENT).run(call, "lookup_agreement",
                                         '{"question": "late fee kitna hai"}')
    assert r.ok and r.content["cite_as"] == "Section 4"
    assert guard.audit.for_call(call)[-1]["detail"].startswith("4")


def test_agent_answers_from_the_agreement(guard, calls, account):
    model = FakeModel(tool("lookup_agreement", question="late fee"),
                      text("Section 4 ke hisaab se overdue par 2% mahina late fee lagti hai."))
    agent, _ = Agent.start(guard=guard, calls=calls, model=model, borrower_id=account[0],
                           loan_id=account[1], channel="chat", agreement=AGREEMENT)
    t = agent.handle("Late fee kitni lagti hai?")
    assert t.tool_calls == ["lookup_agreement"] and "Section 4" in t.reply


def test_without_an_agreement_the_tool_refuses_politely(guard, calls, account):
    model = FakeModel(tool("lookup_agreement", question="late fee"),
                      text("Main yeh team se confirm karwa deti hoon."))
    agent, _ = start(guard, calls, account, model)
    assert agent.handle("late fee?").refused == ["no_agreement"]
