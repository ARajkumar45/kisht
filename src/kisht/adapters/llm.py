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
                 disable_thinking: bool = True, name: str | None = None):
        self.name = name or model
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        # Qwen-style servers: switch "thinking" off (D73: 2.4x slower for no gain on our task).
        self.extra_body = ({"chat_template_kwargs": {"enable_thinking": False}}
                           if disable_thinking else None)
        self.client = openai.OpenAI(base_url=base_url, api_key=api_key or "local",
                                    timeout=timeout_s, max_retries=1)

    def complete(self, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]] | None = None) -> ModelReply:
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages,
                                  "max_tokens": self.max_tokens,
                                  "temperature": self.temperature}
        if tools:
            kwargs["tools"] = tools
        if self.extra_body:
            kwargs["extra_body"] = self.extra_body
        started = time.perf_counter()
        try:
            resp = self.client.chat.completions.create(**kwargs)
        except openai.OpenAIError as e:
            raise ModelUnavailable(f"{type(e).__name__}: {e}") from e
        latency = time.perf_counter() - started
        if not resp.choices:
            raise ModelUnavailable("server returned no choices")
        msg = resp.choices[0].message
        usage = resp.usage
        details = getattr(usage, "prompt_tokens_details", None) if usage else None
        return ModelReply(
            content=_THINK.sub("", msg.content or "").strip(),
            tool_calls=[ToolCall(tc.id or f"call_{i}", tc.function.name,
                                 tc.function.arguments or "{}")
                        for i, tc in enumerate(msg.tool_calls or [])],
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
        self._lock = threading.Lock()
        self.in_flight = 0
        self.waiting = 0

    def acquire(self) -> float:
        """Wait for a free slot; returns seconds waited. Raises ModelUnavailable on timeout."""
        started = time.perf_counter()
        with self._lock:
            self.waiting += 1
        try:
            if not self._sem.acquire(timeout=self.queue_timeout_s):
                raise ModelUnavailable(
                    f"model server busy: no free slot within {self.queue_timeout_s:.0f}s "
                    f"({self.max_concurrency} in flight)")
        finally:
            with self._lock:
                self.waiting -= 1
        with self._lock:
            self.in_flight += 1
        return time.perf_counter() - started

    def release(self) -> None:
        with self._lock:
            self.in_flight -= 1
        self._sem.release()


class LimitedModel:
    """Wraps a ChatModel so it only runs when its server has a free slot."""

    def __init__(self, inner: ChatModel, slots: ServerSlots):
        self.inner = inner
        self.slots = slots
        self.name = inner.name

    def complete(self, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]] | None = None) -> ModelReply:
        waited = self.slots.acquire()
        try:
            reply = self.inner.complete(messages, tools)
        finally:
            self.slots.release()
        reply.queue_wait_s = waited
        return reply


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
