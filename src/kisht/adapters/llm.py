"""LLM adapter: any OpenAI-compatible server (MLX on this Mac, Ollama, llama.cpp, vLLM, a cloud API).

Two things every server gets, learned in M4 (D79, D80):
  - a concurrency limit shared by every role that uses the same server, with a bounded wait:
    this Mac handles 1-2 conversations at once and its GPU runs out of memory beyond that;
  - a health check that runs a tiny real completion (listing models stayed "healthy" while
    every completion failed).
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any

import openai

from kisht.ports import ChatModel, ModelReply, ModelUnavailable, ToolCall

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


class OpenAICompatibleModel:
    """One model on one OpenAI-compatible server. Holds no conversation state."""

    def __init__(self, *, base_url: str, model: str, api_key: str = "local",
                 timeout_s: float = 60.0, max_tokens: int = 400, temperature: float = 0.3,
                 disable_thinking: bool = True, name: str | None = None,
                 max_retries: int = 1):
        self.name = name or model
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        # Qwen-style servers: switch "thinking" off (D73: 2.4x slower for no gain on our task).
        self.extra_body = ({"chat_template_kwargs": {"enable_thinking": False}}
                           if disable_thinking else None)
        self.client = openai.OpenAI(base_url=base_url, api_key=api_key or "local",
                                    timeout=timeout_s, max_retries=max_retries)

    def reachable(self) -> bool:
        """Does the server answer at all? Cheap; says nothing about generating (health_check)."""
        try:
            self.client.with_options(timeout=1.5, max_retries=0).models.list()
        except openai.OpenAIError:
            return False
        return True

    def warm(self, messages: list[dict[str, Any]],
             tools: list[dict[str, Any]] | None = None) -> None:
        """Make the server read (and cache) a prompt without writing an answer."""
        try:
            self.complete(messages, tools, max_tokens=1)
        except ModelUnavailable:
            pass

    def _request(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
                 max_tokens: int | None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages,
                                  "max_tokens": max_tokens or self.max_tokens,
                                  "temperature": self.temperature}
        if tools:
            kwargs["tools"] = tools
        if self.extra_body:
            kwargs["extra_body"] = self.extra_body
        return kwargs

    def complete(self, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]] | None = None, *,
                 max_tokens: int | None = None) -> ModelReply:
        started = time.perf_counter()
        try:
            resp = self.client.chat.completions.create(**self._request(messages, tools, max_tokens))
        except openai.OpenAIError as e:
            raise ModelUnavailable(f"{type(e).__name__}: {e}") from e
        latency = time.perf_counter() - started
        if not resp.choices:
            raise ModelUnavailable("server returned no choices")
        msg = resp.choices[0].message
        return self._reply(msg.content, [(tc.id, tc.function.name, tc.function.arguments)
                                         for tc in msg.tool_calls or []], resp.usage, latency)

    def stream(self, messages: list[dict[str, Any]],
               tools: list[dict[str, Any]] | None = None, *, on_text: Any) -> ModelReply:
        """Like complete, but hands each piece of text to on_text as the model writes it, so
        a voice call can start speaking the first sentence while the rest is being written
        (measured: the first word comes after 0.1-0.5 s, the whole reply after 2-3 s)."""
        kwargs = self._request(messages, tools, None)
        kwargs.update(stream=True, stream_options={"include_usage": True})
        started = time.perf_counter()
        text, usage, calls = "", None, {}
        try:
            for chunk in self.client.chat.completions.create(**kwargs):
                usage = getattr(chunk, "usage", None) or usage
                for choice in chunk.choices or []:
                    delta = choice.delta
                    if delta is None:
                        continue
                    if delta.content:
                        text += delta.content
                        on_text(delta.content)
                    for tc in delta.tool_calls or []:
                        fn = tc.function
                        index = tc.index if tc.index is not None else (
                            len(calls) if fn and fn.name else max(len(calls) - 1, 0))
                        slot = calls.setdefault(index, {"id": None, "name": "", "arguments": ""})
                        slot["id"] = tc.id or slot["id"]
                        if fn:
                            slot["name"] += fn.name or ""
                            slot["arguments"] += fn.arguments or ""
        except openai.OpenAIError as e:
            raise ModelUnavailable(f"{type(e).__name__}: {e}") from e
        return self._reply(text, [(c["id"], c["name"], c["arguments"])
                                  for _, c in sorted(calls.items())], usage,
                           time.perf_counter() - started)

    @staticmethod
    def _reply(content: str | None, calls: list[tuple], usage: Any, latency: float) -> ModelReply:
        details = getattr(usage, "prompt_tokens_details", None) if usage else None
        return ModelReply(
            content=_THINK.sub("", content or "").strip(),
            tool_calls=[ToolCall(cid or f"call_{i}", name, args or "{}")
                        for i, (cid, name, args) in enumerate(calls)],
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            cached_tokens=(getattr(details, "cached_tokens", 0) or 0) if details else 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            latency_s=latency)


class ServerSlots:
    """How many requests one model server may run at once. Shared by all roles on that server."""

    def __init__(self, max_concurrency: int, queue_timeout_s: float):
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self.max_concurrency = max_concurrency
        self.queue_timeout_s = queue_timeout_s
        self._sem = threading.BoundedSemaphore(max_concurrency)
        # Background work may use all slots but one (all of them if there is only one).
        self._background = threading.BoundedSemaphore(max(1, max_concurrency - 1))
        self._lock = threading.Lock()
        self.in_flight = 0
        self.waiting = 0

    def acquire(self, *, timeout_s: float | None = None, background: bool = False) -> float:
        """Wait for a free slot; returns seconds waited. Raises ModelUnavailable on timeout."""
        started = time.perf_counter()
        limit = timeout_s or self.queue_timeout_s
        with self._lock:
            self.waiting += 1
        try:
            if background and not self._background.acquire(timeout=limit):
                raise ModelUnavailable(f"model server busy: background work waited {limit:.0f}s")
            left = max(0.01, limit - (time.perf_counter() - started))
            if not self._sem.acquire(timeout=left):
                if background:
                    self._background.release()
                raise ModelUnavailable(
                    f"model server busy: no free slot within {limit:.0f}s "
                    f"({self.max_concurrency} in flight)")
        finally:
            with self._lock:
                self.waiting -= 1
        with self._lock:
            self.in_flight += 1
        return time.perf_counter() - started

    def release(self, *, background: bool = False) -> None:
        with self._lock:
            self.in_flight -= 1
        self._sem.release()
        if background:
            self._background.release()


class LimitedModel:
    """Wraps a ChatModel so it only runs when its server has a free slot."""

    def __init__(self, inner: ChatModel, slots: ServerSlots, *, background: bool = False,
                 queue_timeout_s: float | None = None):
        self.inner = inner
        self.slots = slots
        self.background = background
        self.queue_timeout_s = queue_timeout_s
        self.name = inner.name

    def _run(self, call: Any) -> ModelReply:
        waited = self.slots.acquire(timeout_s=self.queue_timeout_s, background=self.background)
        try:
            reply = call()
        finally:
            self.slots.release(background=self.background)
        reply.queue_wait_s = waited
        return reply

    def complete(self, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]] | None = None) -> ModelReply:
        return self._run(lambda: self.inner.complete(messages, tools))

    def stream(self, messages: list[dict[str, Any]],
               tools: list[dict[str, Any]] | None = None, *, on_text: Any) -> ModelReply:
        inner = getattr(self.inner, "stream", None)
        return self._run(lambda: inner(messages, tools, on_text=on_text) if inner
                         else self.inner.complete(messages, tools))

    def reachable(self) -> bool:
        reach = getattr(self.inner, "reachable", None)
        return bool(reach()) if reach else True

    def warm(self, messages: list[dict[str, Any]],
             tools: list[dict[str, Any]] | None = None) -> None:
        warm = getattr(self.inner, "warm", None)
        if warm and self.slots.in_flight < self.slots.max_concurrency:   # never queue for this
            try:
                self._run(lambda: warm(messages, tools) or ModelReply(content=""))
            except ModelUnavailable:
                pass


def health_check(model: ChatModel) -> dict[str, Any]:
    """Run a tiny real completion. Only this proves the server can actually generate."""
    started = time.perf_counter()
    try:
        reply = model.complete([{"role": "user", "content": "Reply with the single word OK."}])
    except ModelUnavailable as e:
        return {"ok": False, "model": model.name, "error": str(e),
                "seconds": round(time.perf_counter() - started, 2)}
    return {"ok": bool(reply.content), "model": model.name, "reply": reply.content[:20],
            "seconds": round(time.perf_counter() - started, 2)}
