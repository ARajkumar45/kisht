"""The bridge Bolna talks to, exercised with FastAPI's test client and a scripted model."""
import json

import fakeredis
import pytest
from conftest import SALON
from fastapi.testclient import TestClient
from test_session import DETAILS, READ_BACK, FakeModel, text, tool

from receptionist.audit import AuditLog
from receptionist.bookings import SqliteBookingStore
from receptionist.bridge import Bridge, chunk_text, create_app, last_user_text
from receptionist.business import BusinessRegistry, load_business
from receptionist.notebook import CallStore

WELCOME = {"role": "assistant", "content": "Hello, Glow Salon. How can I help you?"}
SYSTEM = {"role": "system", "content": "## Agent Prompt: ... ## Transcript:"}


def make(model):
    calls = CallStore(fakeredis.FakeRedis(decode_responses=True))
    bridge = Bridge(BusinessRegistry([load_business(SALON)]), calls, SqliteBookingStore(),
                    AuditLog(), model)
    return bridge, TestClient(create_app(bridge))


def bolna_request(user_lines, run_id="run-1", stream=True):
    """What Bolna sends: system + welcome + alternating turns, the caller's line last."""
    messages = [SYSTEM, WELCOME]
    for i, line in enumerate(user_lines):
        messages.append({"role": "user", "content": line})
        if i < len(user_lines) - 1:
            messages.append({"role": "assistant", "content": "(what Bolna heard us say)"})
    return {"model": "glow-salon", "user": run_id, "stream": stream, "messages": messages}


def sse_text(response):
    chunks = [json.loads(line[6:]) for line in response.text.splitlines()
              if line.startswith("data: ") and line != "data: [DONE]"]
    content = "".join(c["choices"][0]["delta"].get("content", "")
                      for c in chunks if c["choices"])
    assert response.text.rstrip().endswith("data: [DONE]")
    assert any(c["choices"] and c["choices"][0]["finish_reason"] == "stop" for c in chunks)
    assert any(not c["choices"] and "usage" in c for c in chunks)
    return content


def test_first_request_starts_a_call_and_streams_the_reply():
    bridge, client = make(FakeModel(text("We're open 10 to 8 on weekdays.")))
    r = client.post("/v1/chat/completions", json=bolna_request(["What are your timings?"]))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert sse_text(r) == "We're open 10 to 8 on weekdays."
    call_id = bridge.calls.r.get("bolna:run:run-1")
    roles = [m["role"] for m in bridge.calls.messages(call_id)]
    assert roles == ["assistant", "user", "assistant"]          # greeting, caller, reply


def test_only_the_latest_caller_line_is_used_and_our_notebook_is_the_truth():
    model = FakeModel(text("Rs 300."), text("Yes, card and UPI."))
    _bridge, client = make(model)
    client.post("/v1/chat/completions", json=bolna_request(["price of men's haircut?"]))
    client.post("/v1/chat/completions",
                json=bolna_request(["price of men's haircut?", "do you take UPI?"]))
    second_request_to_model = model.requests[1]
    assert second_request_to_model[-1] == {"role": "user", "content": "do you take UPI?"}
    assert "(what Bolna heard us say)" not in json.dumps(second_request_to_model)
    assert any(m["content"] == "Rs 300." for m in second_request_to_model)   # our own reply


def test_two_runs_are_two_calls():
    bridge, client = make(FakeModel(text("a"), text("b")))
    client.post("/v1/chat/completions", json=bolna_request(["hi"], run_id="run-A"))
    client.post("/v1/chat/completions", json=bolna_request(["hi"], run_id="run-B"))
    a = bridge.calls.r.get("bolna:run:run-A")
    b = bridge.calls.r.get("bolna:run:run-B")
    assert a and b and a != b


def test_full_booking_over_the_bridge():
    model = FakeModel(tool("book_visit", **DETAILS), text(READ_BACK + ". Shall I book it?"))
    bridge, client = make(model)
    r1 = client.post("/v1/chat/completions",
                     json=bolna_request(["Haircut kal 11 baje, Priya, 9845012345"]))
    assert "Shall I book it?" in sse_text(r1)
    r2 = client.post("/v1/chat/completions",
                     json=bolna_request(["Haircut kal 11 baje, Priya, 9845012345", "haan, book kar do"]))
    assert sse_text(r2).startswith("Ho gaya, book kar diya")
    call_id = bridge.calls.r.get("bolna:run:run-1")
    assert bridge.bookings.get(bridge.calls.get(call_id, "booking_id")).customer_name == "Priya"
    actions = [e["action"] for e in bridge.audit.for_call(call_id)]
    assert actions == ["propose_booking", "bridge_turn", "caller_yes", "confirm_booking",
                       "bridge_turn"]


def test_non_streaming_request_returns_a_plain_completion():
    _, client = make(FakeModel(text("Hello!")))
    r = client.post("/v1/chat/completions", json=bolna_request(["hi"], stream=False))
    assert r.json()["choices"][0]["message"]["content"] == "Hello!"


def test_missing_user_field_still_works_with_a_default_run():
    bridge, client = make(FakeModel(text("ok")))
    body = bolna_request(["hi"])
    del body["user"]
    assert client.post("/v1/chat/completions", json=body).status_code == 200
    assert bridge.calls.r.get("bolna:run:unpatched-default")


def test_unknown_business_and_no_user_message_are_rejected():
    _, client = make(FakeModel())
    body = bolna_request(["hi"])
    body["model"] = "nope"
    assert client.post("/v1/chat/completions", json=body).status_code == 404
    assert client.post("/v1/chat/completions",
                       json={"model": "glow-salon", "messages": [SYSTEM]}).status_code == 400


def test_models_and_health():
    _, client = make(FakeModel(text("OK")))
    assert [m["id"] for m in client.get("/v1/models").json()["data"]] == ["glow-salon"]
    h = client.get("/health")
    assert h.status_code == 200 and h.json()["ok"] and h.json()["model_reply"] == "OK"


def test_health_reports_a_dead_model():
    from receptionist.model_client import ModelUnavailable
    _, client = make(FakeModel(ModelUnavailable("connection refused")))
    h = client.get("/health")
    assert h.status_code == 503 and not h.json()["ok"]


@pytest.mark.parametrize("text_, expect", [
    ("short", ["short"]),
    ("one two three four five six seven eight nine ten eleven twelve",
     ["one two three four five six seven eight nine", " ten eleven twelve"]),
])
def test_chunking_keeps_words_whole_and_text_intact(text_, expect):
    pieces = chunk_text(text_, size=40)
    assert pieces == expect and "".join(pieces) == text_


def test_last_user_text_handles_parts_format_and_blank():
    assert last_user_text([{"role": "user", "content": [{"type": "text", "text": "hi"}]}]) == "hi"
    assert last_user_text([{"role": "user", "content": "   "}]) is None
    assert last_user_text([SYSTEM]) is None


def test_discarded_reply_leaves_the_notebook_as_the_caller_heard_it():
    bridge, client = make(FakeModel(text("first answer"), text("second answer")))
    client.post("/v1/chat/completions", json=bolna_request(["hello"]))
    call_id = bridge.calls.r.get("bolna:run:run-1")
    assert bridge.discard_reply(call_id, "glow-salon", "first answer")
    assert [m["role"] for m in bridge.calls.messages(call_id)] == ["assistant", "user"]
    client.post("/v1/chat/completions", json=bolna_request(["hello", "hello again"]))
    assert bridge.calls.messages(call_id)[-1]["content"] == "second answer"
    assert any(e["action"] == "reply_discarded_unheard" for e in bridge.audit.for_call(call_id))


def test_one_lock_per_call_and_turns_do_not_interleave():
    import threading
    bridge, client = make(FakeModel(text("a"), text("b"), text("c"), text("d")))
    assert bridge.lock_for("run-1") is bridge.lock_for("run-1")
    assert bridge.lock_for("run-1") is not bridge.lock_for("run-2")
    threads = [threading.Thread(target=client.post, args=("/v1/chat/completions",),
                                kwargs={"json": bolna_request(["hello"] * (i + 1))})
               for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    call_id = bridge.calls.r.get("bolna:run:run-1")
    roles = [m["role"] for m in bridge.calls.messages(call_id)]
    assert roles == ["assistant"] + ["user", "assistant"] * 4      # strictly alternating
