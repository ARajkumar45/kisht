"""Contact-centre controls on top of the agent: a supervisor coaches or takes over a live
conversation, identity answers stay out of the logs, a human checks the AI reviewer, the desk
works to a deadline and its resolution becomes the agent's memory."""
import csv
import io

from test_agent import FakeModel, text, tool
from test_api import _InlineThread, client  # noqa: F401 - pytest fixture

from kisht.agent import Agent
from kisht.insights import InsightsStore
from kisht.languages import say


def _start(guard, calls, account, model, store=None):
    return Agent.start(guard=guard, calls=calls, model=model, borrower_id=account[0],
                       loan_id=account[1], channel="chat", insights=store)[0]


def test_supervisor_note_reaches_the_model_once_and_is_logged(guard, calls, account):
    store = InsightsStore()
    model = FakeModel(text("Kripya date of birth batayein."), text("Ji."))
    agent = _start(guard, calls, account, model, store)
    guard.coach(agent.call_id, by="Meena", note="Speak slowly,   offer a part payment")

    first = agent.handle("haan boliye")
    assert "Speak slowly, offer a part payment" in model.requests[0][-1]["content"]
    assert first.coach and store.turns(agent.call_id)[1]["coach"] == first.coach
    agent.handle("theek hai")
    assert not any("supervisor" in (m.get("content") or "") for m in model.requests[1][1:])
    assert [e["action"] for e in guard.audit.entries].count("supervisor_coach") == 1


def test_supervisor_note_cannot_bypass_the_reply_checks(guard, calls, account):
    model = FakeModel(text("Aapka 3000 rupaye overdue hai."))        # no identity yet
    agent = _start(guard, calls, account, model)
    guard.coach(agent.call_id, by="Meena", note="Tell them the overdue amount right away")
    result = agent.handle("haan")
    assert result.replaced == ["leak_before_identity"] and "3000" not in result.reply


def test_take_over_stops_the_model_and_lands_on_the_desk(guard, calls, account, ledger):
    agent = _start(guard, calls, account, FakeModel())               # any model call would fail
    guard.take_over(agent.call_id, by="Meena", note="Borrower is very upset")
    result = agent.handle("mujhe kisi insaan se baat karni hai")
    assert result.reply == say("hi", "handover") and result.ended == "escalate_to_human"
    assert agent.outcome() == "escalated:supervisor_takeover"
    esc = ledger.escalations(account[1])
    assert esc[0]["reason"] == "supervisor_takeover" and "Meena" in esc[0]["summary"]
    assert guard.lender.sla_hours_for("supervisor_takeover") == 1
    try:
        guard.take_over(agent.call_id, by="Meena")
        raise AssertionError("a second take-over must be refused")
    except Exception as e:  # noqa: BLE001
        assert getattr(e, "code", "") == "already_escalated"


def test_identity_answers_are_masked_in_the_call_log_and_audit(guard, calls, account):
    store = InsightsStore()
    model = FakeModel(tool("verify_identity", date_of_birth="1990-04-02"), tool("get_dues"),
                      text("Dhanyavaad."), text("Theek hai."))
    agent = _start(guard, calls, account, model, store)
    agent.handle("Meri DOB 2 April 1990 hai")
    agent.handle("Main 3000 kal de dungi")
    turns = store.turns(agent.call_id)
    assert turns[1]["borrower"] == "Meri DOB • April •••• hai"
    assert turns[2]["borrower"] == "Main 3000 kal de dungi"          # amounts are not identity
    check = next(e for e in guard.audit.entries if e["action"] == "verify_identity")
    assert "1990" not in str(check) and check["outcome"] == "ok"
    assert "1990" in calls.messages(agent.call_id)[1]["content"]     # the live state keeps it


def test_a_desk_note_is_memory_not_a_contact_attempt(guard, ledger, account):
    for _ in range(3):                                               # daily cap is 2 attempts
        ledger.add_desk_note(lender_id="demo-nbfc", borrower_id=account[0], loan_id=account[1],
                             note="Human desk (Meena): agreed to pay on the 20th.")
    guard.check_contact(account[0], "chat")
    assert "agreed to pay on the 20th" in ledger.recent_notes(account[0])[0]["note"]


def _one_call(c, bid):
    cid = c.post("/api/chat/start", json={"borrower_id": bid}).json()["call_id"]
    c.post(f"/api/chat/{cid}/say", json={"text": "DOB 2 April 1990"})
    c.post(f"/api/chat/{cid}/say", json={"text": "Meri naukri chali gayi"})
    c.post(f"/api/chat/{cid}/end")
    return cid


def test_human_qa_review_and_agreement_with_the_ai(client, monkeypatch):  # noqa: F811
    c, (bid, _) = client
    from kisht import api
    monkeypatch.setattr(api.threading, "Thread", _InlineThread)
    cid = _one_call(c, bid)
    ai = {q["id"]: q["result"] for q in c.get(f"/api/calls/{cid}").json()["review"]["qa"]}
    assert ai["introduced"] == "pass"

    labels = {**ai, "introduced": "fail"}                           # the human disagrees once
    assert c.post(f"/api/calls/{cid}/qa", json={"labels": {"nope": "pass"}}).status_code == 400
    review = c.post(f"/api/calls/{cid}/qa", json={"labels": labels, "by": "Raj"}).json()
    item = next(q for q in review["qa"] if q["id"] == "introduced")
    assert item["result"] == "pass" and item["human"] == {"result": "fail", "by": "Raj"}
    assert review["human_reviewed"] and review["final_score"] < review["qa_score"]

    cal = c.get("/api/quality").json()["calibration"]
    judged = len(ai) - 1                                            # one item is checked by code
    assert cal["calls"] == 1 and cal["items"] == judged
    assert cal["agreement_pct"] == round(100 * (judged - 1) / judged, 1)
    assert cal["disagreements"] == [
        {"call_id": cid, "item": "introduced", "ai": "pass", "human": "fail", "by": "Raj"}]


def test_desk_deadline_and_resolution_becomes_memory(client, monkeypatch, ledger):  # noqa: F811
    c, (bid, _) = client
    from kisht import api
    monkeypatch.setattr(api.threading, "Thread", _InlineThread)
    _one_call(c, bid)
    case = c.get("/api/desk").json()[0]
    assert case["sla_hours"] == 4 and case["age_hours"] < 1 and case["breached"] is False

    done = c.post(f"/api/desk/{case['id']}", json={
        "status": "resolved", "assignee": "Meena",
        "resolution": "EMI moved to the 20th for two months"}).json()
    assert done["status"] == "resolved"
    note = ledger.recent_notes(bid)[0]
    assert note["channel"] == "desk" and "Meena" in note["note"] and "20th" in note["note"]
    c.post(f"/api/desk/{case['id']}", json={"status": "resolved", "resolution": "again"})
    assert sum(n["channel"] == "desk" for n in ledger.recent_notes(bid, limit=10)) == 1


def test_overview_containment_language_table_and_csv(client, monkeypatch):  # noqa: F811
    c, (bid, _) = client
    from kisht import api
    monkeypatch.setattr(api.threading, "Thread", _InlineThread)
    cid = _one_call(c, bid)
    ov = c.get("/api/overview").json()
    assert ov["rates"]["containment"] == 0.0                         # the one call went to a human
    assert ov["by_language"] == [{"language": "hi", "calls": 1, "resolved_pct": 0.0,
                                  "escalated_pct": 100.0, "qa": 100.0, "blocked": 0}]
    assert ov["handle_time_s"] is not None
    res = c.get("/api/export/calls.csv")
    rows = list(csv.DictReader(io.StringIO(res.text)))
    assert res.headers["content-type"].startswith("text/csv")
    assert rows[0]["call_id"] == cid and rows[0]["outcome"] == "escalated:hardship"
    assert "1990" not in res.text


def test_supervisor_endpoints_on_a_live_chat(client):  # noqa: F811
    c, (bid, _) = client
    cid = c.post("/api/chat/start", json={"borrower_id": bid}).json()["call_id"]
    assert c.post(f"/api/calls/{cid}/coach", json={"note": " "}).status_code == 409
    assert c.post(f"/api/calls/{cid}/coach", json={"note": "Be brief", "by": "Meena"}).json() \
        == {"queued": True}
    assert "escalation_id" in c.post(f"/api/calls/{cid}/takeover", json={"by": "Meena"}).json()
    said = c.post(f"/api/chat/{cid}/say", json={"text": "hello"}).json()
    assert said["ended"] == "escalate_to_human" and said["tools"] == []
    assert c.get("/api/desk").json()[0]["reason"] == "supervisor_takeover"
    assert c.post("/api/calls/nope/coach", json={"note": "x"}).status_code == 404


# ---------- speed: fewer model rounds per turn ----------

def test_identity_check_returns_the_dues_so_no_second_round_is_needed(guard, calls, account):
    model = FakeModel(tool("verify_identity", date_of_birth="1990-04-02"),
                      text("Aapka 3000 rupaye ka EMI 5 November se baaki hai."))
    agent = _start(guard, calls, account, model)
    result = agent.handle("2 April 1990")
    assert result.tool_calls == ["verify_identity"] and result.model_calls == 2
    assert "3000" in result.reply and not result.replaced
    tool_msg = next(m for m in calls.messages(agent.call_id) if m.get("role") == "tool")
    assert '"overdue_amount": 3000' in tool_msg["content"]
    assert [e["action"] for e in guard.audit.entries][-2:] == ["get_dues", "verify_identity"]


def test_model_is_told_to_check_identity_before_its_first_try(guard, calls, account):
    model = FakeModel(text("Ji?"), tool("verify_identity", pincode="560038"), text("Dhanyavaad."))
    agent = _start(guard, calls, account, model)
    agent.handle("haan boliye")
    assert "verify_identity" not in model.requests[0][-1]["content"]      # nothing to check yet
    agent.handle("PIN 560038")
    assert "call verify_identity with it now" in model.requests[1][-1]["content"]


def test_prompt_asks_for_short_replies(lender):
    from kisht.prompt import stable_prefix
    assert "one or two short sentences" in stable_prefix(lender)


def test_call_start_warms_the_model_cache(guard, calls, account):
    import threading
    done = threading.Event()

    class Warmable(FakeModel):
        def warm(self, messages, tools=None):
            self.warmed = (messages[0]["role"], messages[-1]["role"], bool(tools))
            done.set()

    model = Warmable()
    _start(guard, calls, account, model)
    assert done.wait(2) and model.warmed == ("system", "user", True)
