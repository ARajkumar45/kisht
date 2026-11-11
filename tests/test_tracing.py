"""Every turn becomes a trace in the insights store: the turn span, each model call and tool
call inside it, the reply check; all turns of one call share one trace id."""
import json

from test_agent import FakeModel, text, tool

from kisht.agent import Agent
from kisht.insights import InsightsStore
from kisht.tracing import setup_tracing, trace_id_for


def test_a_call_is_logged_and_traced(guard, calls, account):
    store = InsightsStore()
    setup_tracing(store)
    model = FakeModel(tool("verify_identity", date_of_birth="1990-04-02"), tool("get_dues"),
                      text("Dhanyavaad Priya ji. Rs 3000 baaki hai."), text("Note."))
    agent, greeting = Agent.start(guard=guard, calls=calls, model=model, borrower_id=account[0],
                                  loan_id=account[1], channel="chat", insights=store)
    agent.handle("Haan main Priya, DOB 2 April 1990")
    agent.finish()

    call = store.call(agent.call_id)
    assert call["status"] == "ended" and call["turns"] == 1 and call["borrower_name"]
    turns = store.turns(agent.call_id)
    assert turns[0]["agent"] == greeting and turns[1]["tools"] == ["verify_identity", "get_dues"]

    spans = store.spans(agent.call_id)
    names = [s["name"] for s in spans]
    assert names.count("chat") == 3 and names.count("execute_tool") == 2
    assert {"turn", "reply_check", "case_note"} <= set(names)
    assert {s["trace_id"] for s in spans} == {f"{trace_id_for(agent.call_id):032x}"}
    turn = next(s for s in spans if s["name"] == "turn")
    children = [s for s in spans if s["parent_id"] == turn["span_id"]]
    assert {s["name"] for s in children} == {"chat", "execute_tool", "reply_check"}
    tool_span = next(s for s in spans if s["name"] == "execute_tool")
    assert tool_span["attrs"]["gen_ai.tool.name"] == "verify_identity"
    assert json.dumps(spans)                                      # all JSON-serialisable


def test_a_guard_refusal_marks_the_tool_span_as_an_error(guard, calls, account):
    store = InsightsStore()
    setup_tracing(store)
    model = FakeModel(tool("verify_identity", date_of_birth="1999-01-01"),
                      text("Woh match nahi hua. PIN bata sakti hain?"))
    agent, _ = Agent.start(guard=guard, calls=calls, model=model, borrower_id=account[0],
                           loan_id=account[1], channel="chat", insights=store)
    agent.handle("1 Jan 1999")
    span = next(s for s in store.spans(agent.call_id) if s["name"] == "execute_tool")
    assert span["status"] == "ERROR" and span["attrs"]["kisht.refused"] == "identity_mismatch"
    assert store.call(agent.call_id)["blocks"] == 1


def test_silent_live_calls_are_closed_as_abandoned():
    store = InsightsStore()
    store.open_call(call_id="c1", lender_id="x", borrower_id=None, loan_id=None,
                    borrower_name="A", channel="chat", language="en", greeting="Hi")
    store.db.execute("UPDATE turns SET at_utc='2020-01-01T00:00:00+00:00'")
    store.open_call(call_id="c2", lender_id="x", borrower_id=None, loan_id=None,
                    borrower_name="B", channel="chat", language="en", greeting="Hi")
    assert store.close_stale(30) == 1
    assert store.call("c1")["outcome"] == "abandoned" and store.call("c2")["status"] == "live"
