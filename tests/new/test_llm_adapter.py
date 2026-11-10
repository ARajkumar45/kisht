import threading
import time

import pytest

from kisht.adapters.llm import LimitedModel, ServerSlots, health_check
from kisht.ports import ModelReply, ModelUnavailable


class SlowModel:
    """Fake model: records how many requests run at the same time."""

    def __init__(self, seconds=0.05):
        self.name = "fake"
        self.seconds = seconds
        self.now = 0
        self.peak = 0
        self.lock = threading.Lock()

    def complete(self, messages, tools=None):
        with self.lock:
            self.now += 1
            self.peak = max(self.peak, self.now)
        time.sleep(self.seconds)
        with self.lock:
            self.now -= 1
        return ModelReply(content="OK")


def run_parallel(fn, n):
    errors = []

    def wrapped():
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - collected for the assertion
            errors.append(e)
    threads = [threading.Thread(target=wrapped) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


def test_server_never_runs_more_than_its_slots():
    inner = SlowModel()
    model = LimitedModel(inner, ServerSlots(max_concurrency=2, queue_timeout_s=5))
    assert run_parallel(lambda: model.complete([{"role": "user", "content": "hi"}]), 10) == []
    assert inner.peak == 2


def test_roles_on_one_server_share_its_slots():
    """Agent and simulator on the same Mac share one GPU, so they share the limit."""
    inner_a, inner_b = SlowModel(), SlowModel()
    slots = ServerSlots(max_concurrency=1, queue_timeout_s=5)
    agent, simulator = LimitedModel(inner_a, slots), LimitedModel(inner_b, slots)
    lock = threading.Lock()
    seen = {"together": 0}

    def call(m):
        m.complete([])
        with lock:
            seen["together"] = max(seen["together"], inner_a.now + inner_b.now + 1)
    assert run_parallel(lambda: call(agent), 3) == []
    assert run_parallel(lambda: call(simulator), 3) == []
    assert inner_a.peak == 1 and inner_b.peak == 1


def test_full_queue_fails_fast_instead_of_piling_up():
    model = LimitedModel(SlowModel(seconds=0.5), ServerSlots(max_concurrency=1, queue_timeout_s=0.1))
    errors = run_parallel(lambda: model.complete([]), 3)
    assert errors and all(isinstance(e, ModelUnavailable) for e in errors)
    assert "busy" in str(errors[0])


def test_queue_wait_is_reported():
    model = LimitedModel(SlowModel(seconds=0.1), ServerSlots(max_concurrency=1, queue_timeout_s=5))
    replies = []
    run_parallel(lambda: replies.append(model.complete([])), 2)
    assert max(r.queue_wait_s for r in replies) >= 0.05


def test_slots_are_released_after_an_error():
    class Broken:
        name = "broken"

        def complete(self, messages, tools=None):
            raise ModelUnavailable("down")
    slots = ServerSlots(max_concurrency=1, queue_timeout_s=0.1)
    model = LimitedModel(Broken(), slots)
    for _ in range(3):
        with pytest.raises(ModelUnavailable, match="down"):
            model.complete([])
    assert slots.in_flight == 0


def test_health_check_needs_a_real_completion():
    class Down:
        name = "down"

        def complete(self, messages, tools=None):
            raise ModelUnavailable("404 generation thread died")
    assert health_check(SlowModel(0))["ok"] is True
    bad = health_check(Down())
    assert bad["ok"] is False and "404" in bad["error"]
