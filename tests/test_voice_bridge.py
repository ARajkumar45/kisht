import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from kisht_support import IST
from test_agent import FakeModel, text, tool

from kisht.lender import LenderRegistry
from kisht.voice_bridge import VoiceBridge, chunk_text, create_app, last_user_text


def make(guard, calls, model):
    bridge = VoiceBridge(lenders=LenderRegistry([guard.lender]), guards={"demo-nbfc": guard},
                         calls=calls, model=model)
    return bridge, TestClient(create_app(bridge))


def request(lines, run="run-1", target="demo-nbfc:br_1", stream=True):
    messages = [{"role": "system", "content": "unused"},
                {"role": "assistant", "content": "welcome"}]
    for i, line in enumerate(lines):
        messages.append({"role": "user", "content": line})
        if i < len(lines) - 1:
            messages.append({"role": "assistant", "content": "(what Bolna heard)"})
    return {"model": target, "user": run, "stream": stream, "messages": messages}


def sse(resp):
    out = ""
    for line in resp.text.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            d = json.loads(line[6:])
            if d["choices"]:
                out += d["choices"][0]["delta"].get("content", "") or ""
    return out


def test_voice_call_runs_the_same_agent_and_guard(guard, calls, account, ledger):
    model = FakeModel(tool("verify_identity", pincode="560038"), tool("get_dues"),
                      text("Aapki 5 November ki EMI Rs 3000 baaki hai."),
                      tool("record_promise_to_pay", amount=3000, pay_date="2026-11-14"),
                      text("So Rs 3000 on Saturday 14 November. Sahi hai?"),
                      tool("schedule_followup", on_date="2026-11-15", reason="check"),
                      text("Dhanyavaad!"))
    _, client = make(guard, calls, model)
    assert "Rs 3000" in sse(client.post("/v1/chat/completions", json=request(["PIN 560038"])))
    client.post("/v1/chat/completions", json=request(["PIN 560038", "14 ko 3000"]))
    r = sse(client.post("/v1/chat/completions", json=request(["PIN 560038", "14 ko", "haan ji"])))
    assert r.startswith("Dhanyavaad, note kar liya: Rs 3000")
    assert len(ledger.open_promises(account[1])) == 1
    call_id = calls.r.get("bolna:run:run-1")
    assert calls.get(call_id, "channel") == "voice"


def test_two_calls_do_not_mix(guard, calls, account):
    _, client = make(guard, calls, FakeModel(text("a"), text("b")))
    client.post("/v1/chat/completions", json=request(["hi"], run="r1"))
    client.post("/v1/chat/completions", json=request(["hi"], run="r2"))
    assert calls.r.get("bolna:run:r1") != calls.r.get("bolna:run:r2")


def test_contact_rules_apply_to_voice(guard, calls, account, clock):
    clock["now"] = datetime(2026, 11, 10, 21, 0, tzinfo=IST)
    _, client = make(guard, calls, FakeModel())
    r = client.post("/v1/chat/completions", json=request(["hello"], stream=False))
    assert r.json()["choices"][0]["message"]["content"].startswith("Maaf kijiye, abhi baat")


@pytest.mark.parametrize("target", ["demo-nbfc", "nope:br_1", ""])
def test_bad_targets_are_rejected(guard, calls, account, target):
    _, client = make(guard, calls, FakeModel())
    assert client.post("/v1/chat/completions",
                       json=request(["hi"], target=target)).status_code == 404


def test_helpers():
    assert last_user_text([{"role": "user", "content": [{"type": "text", "text": "hi"}]}]) == "hi"
    assert "".join(chunk_text("one two three four " * 5)) == "one two three four " * 5


# ---------- hardening found by the audit before the first real phone call ----------

def test_a_run_id_is_bound_to_its_borrower_and_a_closed_call_is_not_reused(guard, calls, ledger,
                                                                            account):
    """Unpatched Bolna sends no run id, so every call arrived as "unpatched-default" and the
    next borrower continued the previous borrower's verified conversation."""
    from kisht_support import make_account
    other = make_account(ledger, borrower_id="br_2", loan_id="ln_2")
    model = FakeModel(tool("verify_identity", pincode="560038"), text("Aapki EMI Rs 3000 hai."),
                      text("Kripya janm tithi bataiye."), text("Ji."))
    _, client = make(guard, calls, model)
    client.post("/v1/chat/completions", json=request(["PIN 560038"], run=""))
    first = calls.r.get("bolna:run:unpatched-default")
    r = sse(client.post("/v1/chat/completions",
                        json=request(["haan"], run="", target=f"demo-nbfc:{other[0]}")))
    second = calls.r.get("bolna:run:unpatched-default")
    assert second != first and calls.get(second, "borrower_id") == other[0]
    assert not calls.get(second, "identity_verified", False) and "3000" not in r
    calls.end_call(second, "talked")
    client.post("/v1/chat/completions",
                json=request(["haan"], run="", target=f"demo-nbfc:{other[0]}"))
    assert calls.r.get("bolna:run:unpatched-default") != second


def test_any_failure_in_a_turn_is_spoken_as_the_fallback_line_and_logged(guard, calls, account,
                                                                         caplog):
    from kisht.languages import say

    class Broken(FakeModel):
        def complete(self, messages, tools=None):
            raise RuntimeError("database is locked")

    _, client = make(guard, calls, Broken())
    r = client.post("/v1/chat/completions", json=request(["haan"]))
    assert r.status_code == 200 and sse(r) == say("hi", "fallback")
    assert "voice turn failed" in caplog.text and "database is locked" in caplog.text


def test_token_is_required_once_set_and_bad_bodies_are_400(guard, calls, account, monkeypatch):
    _, client = make(guard, calls, FakeModel(text("Ji.")))
    assert client.post("/v1/chat/completions", content=b"not json").status_code == 400
    assert client.post("/v1/chat/completions", json=["x"]).status_code == 400
    assert client.post("/v1/chat/completions",
                       json={"model": "demo-nbfc:br_1", "messages": "x"}).status_code == 400
    monkeypatch.setenv("KISHT_BRIDGE_TOKEN", "s3cret-for-test")
    _, locked = make(guard, calls, FakeModel(text("Ji.")))
    assert locked.post("/v1/chat/completions", json=request(["haan"])).status_code == 401
    assert locked.post("/prepare", json={"model": "demo-nbfc:br_1"}).status_code == 401
    ok = locked.post("/v1/chat/completions", json=request(["haan"]),
                     headers={"Authorization": "Bearer s3cret-for-test"})
    assert ok.status_code == 200 and sse(ok) == "Ji."


def test_health_is_cheap_unless_asked_to_be_deep(guard, calls, account):
    model = FakeModel(text("OK"))
    _, client = make(guard, calls, model)
    assert client.get("/health").json() == {"ok": True, "call_state": True, "model": True}
    assert model.requests == []                       # no completion, no model slot taken
    assert client.get("/health?deep=1").json()["ok"] is True and len(model.requests) == 1


def test_a_turn_stops_when_the_caller_has_gone_and_saves_no_reply(guard, calls, account):
    from kisht.voice_bridge import _CallerGone

    def gone(piece):
        raise _CallerGone

    bridge, _ = make(guard, calls, FakeModel(text("Kripya janm tithi bataiye.")))
    with pytest.raises(_CallerGone):
        bridge.turn("run-9", "demo-nbfc:br_1", "haan", on_say=gone)
    said = [m for m in calls.messages(calls.r.get("bolna:run:run-9")) if m["role"] == "assistant"]
    assert len(said) == 1                             # only the greeting


def test_no_tool_runs_for_a_turn_the_caller_already_talked_over(guard, calls, account, ledger):
    from test_agent import tool

    from kisht.voice_bridge import _CallerGone

    heard = []
    heard_fn = heard.append

    def on_say(piece):
        heard_fn(piece)
    on_say.alive = lambda: False                       # the caller cut in while the model wrote

    bridge, _ = make(guard, calls, FakeModel(tool("opt_out")))
    with pytest.raises(_CallerGone):
        bridge.turn("run-10", "demo-nbfc:br_1", "hmm", on_say=on_say)
    assert not ledger.borrower(account[0])["opted_out"]
