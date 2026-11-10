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
