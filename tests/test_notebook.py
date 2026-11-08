import fakeredis
import pytest

from receptionist.notebook import CallNotFound, CallStore


@pytest.fixture
def store():
    return CallStore(fakeredis.FakeRedis(decode_responses=True), ttl_seconds=600)


def test_new_call_has_state_and_empty_notebook(store):
    call_id = store.start_call("glow-salon", "en", called_number="+918000000001")
    state = store.get_state(call_id)
    assert state["business_id"] == "glow-salon"
    assert state["status"] == "active"
    assert state["stuck_count"] == 0
    assert store.messages(call_id) == []


def test_notebook_keeps_turns_in_order_including_hindi(store):
    call_id = store.start_call("glow-salon", "hi")
    store.append(call_id, {"role": "assistant", "content": "Namaste, Glow Salon."})
    store.append(call_id, {"role": "user", "content": "Kal haircut ka slot hai?"})
    store.append(call_id, {"role": "assistant", "content": None, "tool_calls": [
        {"id": "t1", "type": "function",
         "function": {"name": "check_availability", "arguments": "{}"}}]})
    store.append(call_id, {"role": "tool", "tool_call_id": "t1", "content": "[]"})
    roles = [m["role"] for m in store.messages(call_id)]
    assert roles == ["assistant", "user", "assistant", "tool"]
    assert store.messages(call_id)[1]["content"] == "Kal haircut ka slot hai?"


def test_any_worker_sees_the_same_call(store):
    """Workers are stateless: a second CallStore on the same Redis continues the call."""
    call_id = store.start_call("glow-salon", "en")
    store.append(call_id, {"role": "user", "content": "hello"})
    other_worker = CallStore(store.r)
    assert other_worker.messages(call_id) == [{"role": "user", "content": "hello"}]


def test_calls_do_not_mix(store):
    a = store.start_call("glow-salon", "en")
    b = store.start_call("glow-salon", "en")
    store.append(a, {"role": "user", "content": "from a"})
    assert store.messages(b) == []


def test_rejects_unknown_role(store):
    call_id = store.start_call("glow-salon", "en")
    with pytest.raises(ValueError, match="role"):
        store.append(call_id, {"role": "system", "content": "sneaky"})


def test_unknown_call_raises(store):
    with pytest.raises(CallNotFound):
        store.append("nope", {"role": "user", "content": "hi"})
    with pytest.raises(CallNotFound):
        store.get_state("nope")


def test_state_round_trips_json_values(store):
    call_id = store.start_call("glow-salon", "en")
    pending = {"id": "p1", "service_id": "haircut-men", "start": "2026-11-09T11:00"}
    store.set_state(call_id, pending_booking=pending)
    assert store.get(call_id, "pending_booking") == pending
    store.clear(call_id, "pending_booking")
    assert store.get(call_id, "pending_booking") is None


def test_stuck_counter_is_atomic(store):
    call_id = store.start_call("glow-salon", "en")
    assert store.incr(call_id, "stuck_count") == 1
    assert store.incr(call_id, "stuck_count") == 2
    assert store.get(call_id, "stuck_count") == 2


def test_keys_expire_after_ttl(store):
    call_id = store.start_call("glow-salon", "en")
    store.append(call_id, {"role": "user", "content": "hi"})
    assert 0 < store.r.ttl(f"call:{call_id}:notebook") <= 600
    assert 0 < store.r.ttl(f"call:{call_id}:state") <= 600


def test_end_call_records_outcome(store):
    call_id = store.start_call("glow-salon", "en")
    store.end_call(call_id, outcome="booked")
    state = store.get_state(call_id)
    assert state["status"] == "ended"
    assert state["outcome"] == "booked"


def test_pop_last_removes_only_a_matching_newest_message(store):
    call_id = store.start_call("glow-salon", "en")
    store.append(call_id, {"role": "user", "content": "hi"})
    store.append(call_id, {"role": "assistant", "content": "never heard"})
    assert store.pop_last(call_id, "assistant") == {"role": "assistant", "content": "never heard"}
    assert store.pop_last(call_id, "assistant") is None          # newest is now the user line
    assert store.messages(call_id) == [{"role": "user", "content": "hi"}]
