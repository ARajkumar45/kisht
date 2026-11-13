"""The dashboard API on a real (in-memory) runtime with scripted models: a borrower chats,
the call shows up in the log with its trace and review, an escalation lands on the desk."""
import json

import pytest
from fastapi.testclient import TestClient
from test_agent import FakeModel, text, tool

from kisht.api import create_api
from kisht.audit import AuditLog
from kisht.config import load_config
from kisht.insights import InsightsStore
from kisht.knowledge import Agreement
from kisht.lender import LenderRegistry
from kisht.runtime import Runtime
from kisht.tracing import setup_tracing

REVIEW = {"reason": "job_loss", "sentiment": "distressed", "summary": "Lost job; handed over.",
          "qa": {"introduced": {"result": "pass", "evidence": "Asha"}}}


class Models:
    def __init__(self, **by_role):
        self.by_role = by_role

    def for_role(self, role):
        return self.by_role[role]


@pytest.fixture
def client(guard, calls, ledger, account):
    store = InsightsStore()
    setup_tracing(store)
    agent = FakeModel(
        tool("verify_identity", date_of_birth="1990-04-02"), tool("get_dues"),
        text("Dhanyavaad Priya ji."),
        tool("escalate_to_human", reason="hardship", summary="Lost job, cannot pay"),
        text("Main aapki baat team tak pahuncha rahi hoon."), text("Case note."))
    reviewer = FakeModel(text(json.dumps(REVIEW)),
                         text(json.dumps({"brief": "Lost job.", "next_best_action": "Call back",
                                          "suggested_replies": ["a", "b", "c"]})))
    rt = Runtime(cfg=load_config("config.yaml"), lenders=LenderRegistry.from_dir("lenders"),
                 ledger=ledger, calls=calls, audit=AuditLog(),
                 guards={"demo-nbfc": guard},
                 agreements={"demo-nbfc": Agreement.load("knowledge/demo-nbfc.yaml")},
                 insights=store, models=Models(agent=agent, reviewer=reviewer))
    return TestClient(create_api(rt)), account


def test_chat_then_call_log_trace_review_and_desk(client, monkeypatch):
    c, (bid, _) = client
    from kisht import api
    monkeypatch.setattr(api.threading, "Thread", _InlineThread)       # review runs inline

    start = c.post("/api/chat/start", json={"borrower_id": bid}).json()
    cid = start["call_id"]
    assert start["greeting"]
    assert c.post(f"/api/chat/{cid}/say", json={"text": "DOB 2 April 1990"}).json()["tools"] \
        == ["verify_identity", "get_dues"]
    said = c.post(f"/api/chat/{cid}/say", json={"text": "Meri naukri chali gayi"}).json()
    assert said["ended"] == "escalate_to_human"
    assert c.post(f"/api/chat/{cid}/end").json()["outcome"] == "escalated:hardship"

    log = c.get("/api/calls").json()
    assert log[0]["call_id"] == cid and log[0]["reason"] == "job_loss"
    detail = c.get(f"/api/calls/{cid}").json()
    assert len(detail["turns"]) == 3 and detail["review"]["sentiment"] == "distressed"
    assert {s["name"] for s in detail["spans"]} >= {"turn", "chat", "execute_tool", "review"}
    assert detail["actions"]["escalations"][0]["reason"] == "hardship"

    desk = c.get("/api/desk").json()
    assert desk[0]["team"] == "Hardship team" and desk[0]["status"] == "open"
    eid = desk[0]["id"]
    upd = c.post(f"/api/desk/{eid}", json={"status": "in_progress", "assignee": "Meena"}).json()
    assert upd["status"] == "in_progress" and upd["assignee"] == "Meena"
    assert c.post(f"/api/desk/{eid}/assist").json()["suggested_replies"] == ["a", "b", "c"]

    ov = c.get("/api/overview").json()
    assert ov["ended"] == 1 and ov["rates"]["escalated"] == 100.0
    assert ov["reasons"] == {"job_loss": 1}
    alerts = c.get("/api/live").json()["alerts"]
    assert any(a["kind"] == "escalated:hardship" for a in alerts)


def test_unknown_call_is_404(client):
    c, _ = client
    assert c.get("/api/calls/nope").status_code == 404


class _InlineThread:
    def __init__(self, target, daemon=None):
        self.target = target

    def start(self):
        self.target()


def test_health_reports_what_the_dashboard_depends_on(client, monkeypatch):
    c, _ = client
    from kisht import api

    def down(*a, **k):
        raise api.httpx.ConnectError("refused")

    monkeypatch.setattr(api.httpx, "get", down)
    h = c.get("/api/health").json()
    assert h["model"]["ok"] is False and h["call_state"]["ok"] is True
    assert set(h["clock"]) == {"now", "fixed", "window", "open"}
    assert c.get("/api/overview").json()["speed"]["median_first_words_s"] is None
