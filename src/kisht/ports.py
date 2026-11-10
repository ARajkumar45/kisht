"""Interfaces the core depends on. Adapters implement them; the core never imports an adapter.

Swapping a model server, a speech vendor or a store is a config change (config.yaml),
not a code change, as long as the new adapter honours these interfaces.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class ModelUnavailable(Exception):
    """The model server could not be reached, timed out, errored, or its queue was full."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str          # JSON text, exactly as the model produced it


@dataclass
class ModelReply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    cached_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0      # time inside the model server
    queue_wait_s: float = 0.0   # time waiting for a free slot on that server


class ChatModel(Protocol):
    """Any OpenAI-style chat model. Stateless: every call carries the full message list."""

    name: str

    def complete(self, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]] | None = None) -> ModelReply: ...


class CallState(Protocol):
    """Per-conversation transcript + state, shared by every worker (source of truth)."""

    def start_call(self, tenant_id: str, language: str, **meta: Any) -> str: ...
    def end_call(self, call_id: str, outcome: str) -> None: ...
    def append(self, call_id: str, message: dict[str, Any]) -> None: ...
    def pop_last(self, call_id: str, role: str) -> dict[str, Any] | None: ...
    def messages(self, call_id: str) -> list[dict[str, Any]]: ...
    def get_state(self, call_id: str) -> dict[str, Any]: ...
    def get(self, call_id: str, field: str, default: Any = None) -> Any: ...
    def set_state(self, call_id: str, **fields: Any) -> None: ...
    def clear(self, call_id: str, *fields: str) -> None: ...
    def incr(self, call_id: str, field: str, by: int = 1) -> int: ...
