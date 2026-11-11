"""Conversations get a proper ending whoever ended them: note, ledger close, review, once."""
import json

from test_agent import FakeModel, text, tool

from kisht.agent import Agent
from kisht.audit import AuditLog, entries_for_call
from kisht.insights import InsightsStore
from kisht.review import Reviewer, facts
from kisht.tracing import setup_tracing
from kisht.wrapup import finish_and_review, sweep

REVIEW = json.dumps({"reason": "not_stated", "sentiment": "neutral", "summary": "Ok.",
                     "qa": {"introduced": {"result": "pass", "evidence": "x"}}})


def _talk(guard, calls, account, store, channel="voice"):
    model = FakeModel(tool("verify_identity", date_of_birth="1990-04-02"), tool("get_dues"),
                      text("Aapka EMI Rs 3000 baaki hai."), text("Case note."))
    agent, _ = Agent.start(guard=guard, calls=calls, model=model, borrower_id=account[0],
                           loan_id=account[1], channel=channel, insights=store)
    agent.handle("DOB 2 April 1990")
    return agent, model


def test_a_voice_call_that_goes_quiet_is_finished_and_reviewed_once(guard, calls, account):
    store = InsightsStore()
    agent, model = _talk(guard, calls, account, store)
    kw = {"insights": store, "calls": calls, "guards": {guard.lender.id: guard}, "agent_model": model,
              "reviewer_model": FakeModel(text(REVIEW))}
    assert sweep(**kw) == 0                                   # still fresh: left alone
    assert sweep(**kw, voice_idle_s=0) == 1
    call = store.call(agent.call_id)
    assert call["status"] == "ended" and call["note"] == "Case note."
    assert store.review(agent.call_id)["reason"] == "not_stated"
    assert guard.ledger.recent_notes(account[0])[0]["note"] == "Case note."
    assert sweep(**kw, voice_idle_s=0) == 0                   # nothing left to do


def test_finish_and_review_runs_once_across_processes(guard, calls, account):
    store = InsightsStore()
    agent, _ = _talk(guard, calls, account, store)
    assert finish_and_review(agent, None)["outcome"] == "talked"
    assert finish_and_review(agent, None) is None             # the lock is taken


def test_a_call_whose_state_expired_is_marked_abandoned(guard, calls, account):
    store = InsightsStore()
    store.open_call(call_id="gone", lender_id=guard.lender.id, borrower_id=None, loan_id=None,
                    borrower_name="A", channel="voice", language="en", greeting="Hi")
    assert sweep(insights=store, calls=calls, guards={guard.lender.id: guard},
                 agent_model=FakeModel(), reviewer_model=None, voice_idle_s=0) == 1
    assert store.call("gone")["outcome"] == "abandoned"


def test_get_dues_gives_dates_in_words_with_the_weekday(guard, calls, account):
    store = InsightsStore()
    agent, _ = _talk(guard, calls, account, store)
    words = guard.get_dues(agent.call_id)["dates_in_words"]
    assert words["today"] == "Tuesday 10 November 2026"
    assert words["next_due_date"] == "Saturday 5 December 2026"
    calls.set_state(agent.call_id, language="ta")
    assert guard.get_dues(agent.call_id)["dates_in_words"]["today"] == \
        "செவ்வாய்க்கிழமை, 10 நவம்பர் 2026"
    calls.set_state(agent.call_id, language="te")
    assert guard.get_dues(agent.call_id)["dates_in_words"]["today"] == \
        "మంగళవారం, 10 నవంబర్ 2026"


def test_audit_trail_is_read_from_disk_across_processes(tmp_path):
    a, b = AuditLog(tmp_path / "voice_1.jsonl"), AuditLog(tmp_path / "simday_1.jsonl")
    a.record(call_id="c1", tenant_id="t", action="verify_identity", args={}, outcome="ok")
    b.record(call_id="c1", tenant_id="t", action="get_dues", args={}, outcome="ok")
    b.record(call_id="c2", tenant_id="t", action="get_dues", args={}, outcome="ok")
    assert [e["action"] for e in entries_for_call(tmp_path, "c1")] == ["verify_identity",
                                                                      "get_dues"]


def test_reviewer_is_told_the_record_and_a_rereview_replaces_the_span(guard, calls, account):
    store = InsightsStore()
    setup_tracing(store)
    agent, _ = _talk(guard, calls, account, store)
    agent.finish()
    reviewer_model = FakeModel(text(REVIEW), text(REVIEW))
    reviewer = Reviewer(reviewer_model, store)
    reviewer.review(agent.call_id, guard.lender)
    reviewer.review(agent.call_id, guard.lender)
    assert [s["name"] for s in store.spans(agent.call_id)].count("review") == 1
    prompt = reviewer_model.requests[0][0]["content"]
    assert "Identity WAS verified, in borrower turn 1" in prompt
    assert "No promise to pay was saved" in facts(store.call(agent.call_id),
                                                  store.turns(agent.call_id))


def test_the_command_line_module_imports():
    import kisht.cli  # noqa: F401 - a syntax error here once slipped past the other tests
