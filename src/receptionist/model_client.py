"""Model client for any OpenAI-compatible server (D40).

Default: the local mlx server on this Mac. Switching to a cloud API or vLLM later
is a change of MODEL_BASE_URL / MODEL_NAME / MODEL_API_KEY, not of code.
The model remembers nothing: each call sends the full message list (D34).
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import openai

DEFAULT_BASE_URL = "http://localhost:8080/v1"
DEFAULT_MODEL = "mlx-community/Qwen3.5-9B-4bit"


class ModelUnavailable(Exception):
    """The model server could not be reached or returned an error."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class ModelReply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    cached_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0


class ModelClient(Protocol):
    def complete(self, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]]) -> ModelReply: ...


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


class OpenAICompatibleClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL,
                 api_key: str = "local", timeout_s: float = 30.0, max_tokens: int = 300,
                 temperature: float = 0.3, disable_thinking: bool = True):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.extra_body = ({"chat_template_kwargs": {"enable_thinking": False}}
                           if disable_thinking else None)
        self.client = openai.OpenAI(base_url=base_url, api_key=api_key,
                                    timeout=timeout_s, max_retries=1)

    @classmethod
    def from_env(cls) -> OpenAICompatibleClient:
        return cls(base_url=os.getenv("MODEL_BASE_URL", DEFAULT_BASE_URL),
                   model=os.getenv("MODEL_NAME", DEFAULT_MODEL),
                   api_key=os.getenv("MODEL_API_KEY", "local"))

    def complete(self, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]]) -> ModelReply:
        started = time.perf_counter()
        try:
            resp = self.client.chat.completions.create(
                model=self.model, messages=messages, tools=tools,
                max_tokens=self.max_tokens, temperature=self.temperature,
                extra_body=self.extra_body)
        except openai.OpenAIError as e:
            raise ModelUnavailable(f"{type(e).__name__}: {e}") from e
        latency = time.perf_counter() - started
        msg = resp.choices[0].message
        usage = resp.usage
        details = getattr(usage, "prompt_tokens_details", None) if usage else None
        return ModelReply(
            content=_THINK.sub("", msg.content or "").strip(),
            tool_calls=[ToolCall(tc.id or f"call_{i}", tc.function.name,
                                 tc.function.arguments or "{}")
                        for i, tc in enumerate(msg.tool_calls or [])],
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            cached_tokens=getattr(details, "cached_tokens", 0) or 0 if details else 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            latency_s=latency)
