"""Stage 1 of the production plan: the shortcuts a demo needs are refused unless the config
says `mode: demo`, and four rules no longer depend on timing, on the dashboard's own table, or
on the model choosing the right tool."""
import runpy
import sys

import pytest
import yaml
from fastapi.testclient import TestClient
from test_agent import FakeModel, start, text
from test_config import BASE
from test_guard import refused

from kisht import cli
from kisht.api import create_api
from kisht.audit import AuditLog
from kisht.config import Config, load_config
from kisht.guard import GuardRefused
from kisht.insights import InsightsStore
from kisht.knowledge import Agreement
from kisht.lender import LenderRegistry
from kisht.runtime import Runtime
from kisht.voice_bridge import VoiceBridge, create_app


@pytest.fixture
def production_config(tmp_path):
    path = tmp_path / "prod.yaml"
    path.write_text(yaml.safe_dump(BASE), encoding="utf-8")       # no `mode` line at all
    return str(path)


# ---------- demo shortcuts ----------

def test_a_config_that_does_not_say_demo_is_production():
    assert Config.model_validate(BASE).mode == "production"
    assert load_config("config.yaml").mode == "demo"
    assert load_config("config.docker.yaml").mode == "demo"


@pytest.mark.parametrize("command", [
    ["chat", "--borrower", "br_1", "--at", "2026-11-10T10:00:00+05:30"],
    ["plan", "--at", "2026-11-10T10:00:00+05:30"],
    ["bridge", "--at", "2026-11-10T10:00:00+05:30"],
    ["serve", "--at", "2026-11-10T10:00:00+05:30"],
    ["simulate"],
])
def test_fixed_clock_and_simulated_days_are_refused_in_production(production_config, command):
    with pytest.raises(SystemExit) as e:
        cli.main(["--config", production_config, *command])
    assert "mode: demo" in str(e.value)


def test_bridge_does_not_start_without_a_token_in_production(guard, calls, monkeypatch):
    bridge = VoiceBridge(lenders=LenderRegistry([guard.lender]), guards={"demo-nbfc": guard},
                         calls=calls, model=FakeModel())
    monkeypatch.delenv("KISHT_BRIDGE_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="KISHT_BRIDGE_TOKEN"):
        create_app(bridge, require_token=True)
    create_app(bridge)                                    # demo: allowed, with a printed note
    monkeypatch.setenv("KISHT_BRIDGE_TOKEN", "s3cret")
    create_app(bridge, require_token=True)


def test_made_up_borrowers_are_never_built_from_a_production_config(production_config, tmp_path,
                                                                   monkeypatch):
    db = tmp_path / "ledger.sqlite"
    monkeypatch.setattr(sys, "argv", ["make_loan_book.py", "--config", production_config,
                                      "--db", str(db)])
    with pytest.raises(SystemExit) as e:
        runpy.run_path("tools/make_loan_book.py", run_name="__main__")
    assert "mode: demo" in str(e.value) and not db.exists()


# ---------- attempt caps: counted and logged in one step ----------

def test_attempt_cap_holds_even_when_the_first_check_is_passed_by_two_workers(guard, calls,
                                                                             account, ledger,
                                                                             monkeypatch):
    for _ in range(2):
        guard.start_contact(calls.start_call("demo-nbfc", "hi"), borrower_id=account[0],
                            loan_id=account[1], channel="chat")
    # A second worker read the count before those two were logged: its first check passed.
    monkeypatch.setattr(guard, "check_contact", lambda *a, **k: None)
    before = len(ledger.contacts_since(account[0], "2000"))
    refused("daily_attempt_cap", guard.start_contact, calls.start_call("demo-nbfc", "hi"),
            borrower_id=account[0], loan_id=account[1], channel="chat")
    assert len(ledger.contacts_since(account[0], "2000")) == before      # nothing was logged


def test_a_refused_contact_leaves_no_row(ledger, account):
    def no(_contacts):
        raise GuardRefused("daily_attempt_cap", "full")
    with pytest.raises(GuardRefused):
        ledger.log_contact_checked(no, since_utc="2000", lender_id="demo-nbfc",
                                   borrower_id=account[0], channel="chat")
    assert ledger.contacts_since(account[0], "2000") == []


# ---------- the desk's "resolved" lifts the contact hold ----------

def test_resolving_a_desk_case_lets_the_agent_contact_the_borrower_again(guard, calls, ledger,
                                                                        account):
    rt = Runtime(cfg=load_config("config.yaml"), lenders=LenderRegistry.from_dir("lenders"),
                 ledger=ledger, calls=calls, audit=AuditLog(), guards={"demo-nbfc": guard},
                 agreements={"demo-nbfc": Agreement.load("knowledge/demo-nbfc.yaml")},
                 insights=InsightsStore(), models=None)
    c = TestClient(create_api(rt))
    eid = ledger.add_escalation(loan_id=account[1], reason="hardship", summary="Lost job")
    refused("with_human_desk", guard.check_contact, account[0], "chat")
    c.post(f"/api/desk/{eid}", json={"status": "resolved", "assignee": "Meena",
                                     "resolution": "EMI moved by 30 days"})
    guard.check_contact(account[0], "chat")               # the hold is gone
    c.post(f"/api/desk/{eid}", json={"status": "in_progress"})
    refused("with_human_desk", guard.check_contact, account[0], "chat")   # reopened: held again


# ---------- "stop calling me" is recorded by code ----------

@pytest.mark.parametrize("said", [
    "Stop calling me.",
    "Please don't call me again, I am not interested.",
    "Remove my number from your list",
    "Mujhe dobara call mat karna",
    "aage se phone mat karo",
    "दोबारा कॉल मत करना",
])
def test_a_clear_request_to_stop_is_recorded_without_the_model(guard, calls, account, ledger,
                                                               said):
    agent, _ = start(guard, calls, account, FakeModel())      # the model is never asked
    result = agent.handle(said)
    assert result.ended == "opt_out" and result.tool_calls == ["opt_out"]
    assert ledger.borrower(account[0])["opted_out"]
    assert result.reply == agent.say("opted_out")
    refused("opted_out", guard.check_contact, account[0], "chat")


@pytest.mark.parametrize("said", [
    "Don't call me at work, call in the evening.",
    "Abhi call mat karo, shaam ko karna",
    "I can't talk now, call me tomorrow",
])
def test_not_now_is_not_never(guard, calls, account, ledger, said):
    agent, _ = start(guard, calls, account, FakeModel(text("Sure, when is a good time?")))
    result = agent.handle(said)
    assert result.ended is None and not ledger.borrower(account[0])["opted_out"]


# ---------- a reply the caller never heard takes its read-back with it ----------

def test_an_unheard_read_back_cannot_be_confirmed_later(guard, calls, account):
    bridge = VoiceBridge(lenders=LenderRegistry([guard.lender]), guards={"demo-nbfc": guard},
                         calls=calls, model=FakeModel())
    agent, _ = start(guard, calls, account, FakeModel(), channel="voice")
    calls.set_state(agent.call_id, pending_promise={"amount": 4500, "pay_date": "2026-11-14",
                                                    "read_back": "Rs 4,500 on 14 November?"})
    calls.append(agent.call_id, {"role": "assistant", "content": "Rs 4,500 on 14 November?"})
    assert bridge.discard_reply(agent.call_id)
    assert calls.get(agent.call_id, "pending_promise") is None


# ---------- the dashboard has a login, with roles ----------

VIEW, AGENT, BOSS = "viewer-token-0123456789", "agent-token-0123456789", "boss-token-0123456789"


def _api(guard, calls, ledger, tokens):
    from kisht.api import load_api_tokens
    rt = Runtime(cfg=load_config("config.yaml"), lenders=LenderRegistry.from_dir("lenders"),
                 ledger=ledger, calls=calls, audit=AuditLog(), guards={"demo-nbfc": guard},
                 agreements={"demo-nbfc": Agreement.load("knowledge/demo-nbfc.yaml")},
                 insights=InsightsStore(), models=None)
    return TestClient(create_api(rt, load_api_tokens(tokens)))


def test_with_tokens_set_nothing_is_readable_without_one(guard, calls, ledger, account):
    c = _api(guard, calls, ledger, f"viewer:{VIEW},agent:{AGENT},supervisor:{BOSS}")
    assert c.get("/api/calls").status_code == 401
    assert c.get("/api/calls", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/api/health").status_code == 200                # for probes; no borrower data
    assert c.get("/api/calls", headers={"Authorization": f"Bearer {VIEW}"}).status_code == 200


def test_each_role_can_do_only_its_own_work(guard, calls, ledger, account):
    c = _api(guard, calls, ledger, f"viewer:{VIEW},agent:{AGENT},supervisor:{BOSS}")
    def as_(token):
        return {"Authorization": f"Bearer {token}"}
    eid = ledger.add_escalation(loan_id=account[1], reason="hardship", summary="Lost job")
    assert c.post(f"/api/desk/{eid}", json={"status": "in_progress"},
                  headers=as_(VIEW)).status_code == 403            # a viewer changes nothing
    assert c.post(f"/api/desk/{eid}", json={"status": "in_progress"},
                  headers=as_(AGENT)).status_code == 200
    assert c.get("/api/export/calls.csv", headers=as_(AGENT)).status_code == 403
    assert c.get("/api/export/calls.csv", headers=as_(BOSS)).status_code == 200
    assert c.post("/api/calls/x/coach", json={"note": "hi"}, headers=as_(AGENT)).status_code == 403


def test_a_weak_or_misspelt_token_stops_the_start():
    from kisht.api import load_api_tokens
    for bad in ("viewer:short", "admin:0123456789abcdefgh", "0123456789abcdefgh"):
        with pytest.raises(ValueError):
            load_api_tokens(bad)
    assert load_api_tokens("") == {}


def test_serve_refuses_production_without_tokens(production_config, monkeypatch):
    monkeypatch.delenv("KISHT_API_TOKENS", raising=False)
    with pytest.raises(SystemExit) as e:
        cli.main(["--config", production_config, "serve"])
    assert "KISHT_API_TOKENS" in str(e.value)


def test_a_spreadsheet_formula_in_a_cell_is_exported_as_text():
    from kisht.api import csv_safe
    assert csv_safe('=HYPERLINK("http://x","pay")') == "'=HYPERLINK(\"http://x\",\"pay\")"
    assert csv_safe("+91 98") == "'+91 98" and csv_safe("Asha") == "Asha" and csv_safe(3) == 3


# ---------- identity guesses do not reset by starting a new conversation ----------

def test_three_wrong_identity_answers_lock_the_next_conversation_too(guard, calls, account):
    first = calls.start_call("demo-nbfc", "hi")
    guard.start_contact(first, borrower_id=account[0], loan_id=account[1], channel="chat")
    for _ in range(3):
        refused("identity_mismatch", guard.verify_identity, first, pincode="111111")
    second = calls.start_call("demo-nbfc", "hi")
    guard.start_contact(second, borrower_id=account[0], loan_id=account[1], channel="chat")
    refused("identity_locked", guard.verify_identity, second, pincode="560038")   # even if right


def test_a_right_answer_clears_earlier_wrong_ones(guard, calls, account, ledger):
    call = calls.start_call("demo-nbfc", "hi")
    guard.start_contact(call, borrower_id=account[0], loan_id=account[1], channel="chat")
    refused("identity_mismatch", guard.verify_identity, call, pincode="111111")
    guard.verify_identity(call, pincode="560038")
    assert ledger.identity_failures_since(account[0], "2000") == 0


@pytest.mark.parametrize("said", [
    "If you do not pay we will have you arrested.",
    "Hum aapke rishtedaron ko bata denge.",
    "पुलिस आपके घर आएगी",
])
def test_threats_are_banned_for_every_lender(guard, said):
    assert guard.banned_in(said)


def test_the_dashboard_can_ask_who_it_is_signed_in_as(guard, calls, ledger, account):
    c = _api(guard, calls, ledger, f"agent:{AGENT}")
    assert c.get("/api/me").status_code == 401
    assert c.get("/api/me", headers={"Authorization": f"Bearer {AGENT}"}).json() == {
        "login": True, "role": "agent", "mode": "demo"}
    assert _api(guard, calls, ledger, "").get("/api/me").json()["login"] is False
