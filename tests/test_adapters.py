

def test_background_work_never_takes_the_last_slot_and_live_calls_give_up_fast():
    import threading
    import time

    from kisht.adapters.llm import LimitedModel, ServerSlots
    from kisht.ports import ModelReply, ModelUnavailable

    slots = ServerSlots(max_concurrency=2, queue_timeout_s=30)
    release = threading.Event()

    class Slow:
        name = "slow"

        def complete(self, messages, tools=None):
            release.wait(5)
            return ModelReply(content="done")

    review = LimitedModel(Slow(), slots, background=True)
    threads = [threading.Thread(target=review.complete, args=([],)) for _ in range(2)]
    for t in threads:
        t.start()
    time.sleep(0.1)
    assert slots.in_flight == 1                  # the second review waits; one slot stays free

    class Fast:
        name = "fast"

        def complete(self, messages, tools=None):
            return ModelReply(content="hello")

    assert LimitedModel(Fast(), slots, queue_timeout_s=0.5).complete([]).content == "hello"
    release.set()
    for t in threads:
        t.join()

    one = ServerSlots(max_concurrency=1, queue_timeout_s=30)
    one.acquire()
    started = time.perf_counter()
    try:
        LimitedModel(Fast(), one, queue_timeout_s=0.2).complete([])
        raise AssertionError("must give up")
    except ModelUnavailable:
        assert time.perf_counter() - started < 2
    one.release()


def test_factory_reuses_models_and_gives_live_calls_short_limits():
    from kisht.config import LLMFactory, load_config

    f = LLMFactory(load_config("config.yaml"))
    assert f.for_role("agent") is f.for_role("agent")
    live = f.for_role("agent", live=True)
    assert live is not f.for_role("agent") and live.queue_timeout_s == 5
    assert live.inner.client.max_retries == 0 and live.inner.client.timeout == 20
    assert f.for_role("reviewer").background and not f.for_role("agent").background
