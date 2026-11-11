"""Post-call review: scorecard + tags from the model, compliance facts from code."""
import json

from test_agent import FakeModel, text, tool

from kisht.agent import Agent
from kisht.insights import InsightsStore
from kisht.review import Reviewer, compliance

GOOD = {"reason": "salary_delay", "sentiment": "positive", "summary": "Will pay on the 14th.",
        "qa": {"introduced": {"result": "pass", "evidence": "main Asha"},
               "verified_first": {"result": "fail", "evidence": "model is wrong here"},
               "asked_reason": {"result": "fail", "evidence": "did not ask"},
               "right_handoff": {"result": "na"}}}


def _call(guard, calls, account, store):
    model = FakeModel(tool("verify_identity", date_of_birth="1990-04-02"), tool("get_dues"),
                      text("Aapka EMI Rs 3000 baaki hai."), text("Note."))
    agent, _ = Agent.start(guard=guard, calls=calls, model=model, borrower_id=account[0],
                           loan_id=account[1], channel="chat", insights=store)
    agent.handle("DOB 2 April 1990")
    agent.finish()
    return agent.call_id


def test_review_scores_and_tags_a_call(guard, calls, account):
    store = InsightsStore()
    call_id = _call(guard, calls, account, store)
    review = Reviewer(FakeModel(text("Sure! " + json.dumps(GOOD))), store).review(
        call_id, guard.lender)
    qa = {q["id"]: q for q in review["qa"]}
    assert review["reason"] == "salary_delay" and review["sentiment"] == "positive"
    assert qa["verified_first"]["result"] == "pass" and qa["verified_first"]["by"] == "code"
    assert qa["right_handoff"]["result"] == "na"
    assert review["qa_score"] == 66.7                    # 2 pass, 1 fail; the rest n/a
    assert store.review(call_id)["reason"] == "salary_delay"
    assert store.calls()[0]["qa_score"] == 66.7


def test_bad_json_is_retried_then_recorded_as_unknown(guard, calls, account):
    store = InsightsStore()
    call_id = _call(guard, calls, account, store)
    review = Reviewer(FakeModel(text("I think it went well."), text("still no json")),
                      store).review(call_id, guard.lender)
    assert review["reason"] == "unknown" and review["qa_score"] is None


def test_compliance_counts_blocked_attempts_by_rule():
    turns = [{"replaced": ["banned_phrase"], "refused": []},
             {"replaced": ["false_promise_claim", "unbacked_link_claim"],
              "refused": ["date_out_of_policy", "identity_mismatch"]}]
    by_rule = {c["rule"]: c for c in compliance(turns)}
    assert by_rule["no_threats"]["blocked"] == 1
    assert by_rule["no_false_claims"]["blocked"] == 2
    assert by_rule["within_policy"]["blocked"] == 1
    assert by_rule["privacy"]["status"] == "ok"
