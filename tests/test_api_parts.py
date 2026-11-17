"""The small shared pieces behind the API and the voice bridge."""
import threading

from kisht.api.auth import role_for
from kisht.api.common import Background, TTLCache, json_from
from kisht.insights import InsightsStore
from kisht.keyed_locks import KeyedLocks


def test_ttl_cache_computes_once_per_window():
    now = [0.0]
    cache = TTLCache(5, clock=lambda: now[0])
    calls = []
    compute = lambda: calls.append(1) or len(calls)
    assert cache.get(compute) == 1
    now[0] = 4.9
    assert cache.get(compute) == 1
    now[0] = 5.0
    assert cache.get(compute) == 2


def test_ttl_cache_caches_a_falsy_value():
    cache = TTLCache(60, clock=lambda: 0.0)
    calls = []
    assert cache.get(lambda: calls.append(1) or {}) == {}
    cache.get(lambda: calls.append(1) or {})
    assert len(calls) == 1          # an empty result is still a result


def test_keyed_locks_same_key_same_lock_and_bounded():
    locks = KeyedLocks(limit=3)
    assert locks.get("a") is locks.get("a")
    held = locks.get("b")
    held.acquire()
    locks.get("c")
    locks.get("d")                  # over the limit: unheld locks are dropped, held ones kept
    assert locks.get("b") is held and len(locks) <= 3
    held.release()
    locks.drop("b")
    assert locks.get("b") is not held


def test_background_join_waits_for_running_work():
    done = threading.Event()
    bg = Background()
    bg.run(lambda: done.wait(0.05) or done.set())
    bg.join(2.0)
    assert done.is_set()


def test_role_for_needs_an_exact_token():
    tokens = {"a" * 16: "viewer", "b" * 16: "supervisor"}
    assert role_for(tokens, "b" * 16) == "supervisor"
    assert role_for(tokens, "b" * 15) is None
    assert role_for(tokens, "") is None
    assert role_for(tokens, "ü" * 16) is None      # non-ASCII must not crash the check


def test_json_from_takes_only_an_object():
    assert json_from('Sure: {"brief": "x"} done') == {"brief": "x"}
    assert json_from("[1, 2]") is None
    assert json_from("no json") is None
    assert json_from('{"broken": ') is None


def test_flagged_turns_finds_only_blocked_turns():
    store = InsightsStore()
    for cid in ("c1", "c2"):
        store.open_call(call_id=cid, lender_id="L", borrower_id="B", loan_id="LN",
                        borrower_name="Asha", channel="chat", language="en",
                        greeting="Hello", source="test")
    store.add_turn("c1", borrower="hi", agent="ok")
    store.add_turn("c1", borrower="pay?", agent="safe line", replaced=["false_claim"])
    store.add_turn("c2", borrower="x", agent="no", refused=["R1"])
    rows = store.flagged_turns(["c1", "c2"])
    assert [(r["call_id"], r["replaced"] or r["refused"]) for r in rows] == [
        ("c1", ["false_claim"]), ("c2", ["R1"])]
    assert store.flagged_turns([]) == []
