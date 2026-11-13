"""Conversation transcript ("notebook") and state in Redis — the CallState adapter (D33).

The notebook is the source of truth for the conversation: every turn, in order.
Workers keep nothing important in memory, so any worker can carry on a call
from what is stored here.

Keys per call (all expire DEFAULT_TTL seconds after the last write):
  call:{id}:notebook  Redis list, one JSON message per item (OpenAI chat format)
  call:{id}:state     Redis hash, one JSON value per field
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import redis

DEFAULT_TTL = 24 * 60 * 60
ROLES = {"user", "assistant", "tool"}


class CallNotFound(Exception):
    """No call with this id (never started, or expired)."""


def _notebook_key(call_id: str) -> str:
    return f"call:{call_id}:notebook"


def _state_key(call_id: str) -> str:
    return f"call:{call_id}:state"


class RedisCallState:
    def __init__(self, client: redis.Redis, ttl_seconds: int = DEFAULT_TTL):
        self.r = client
        self.ttl = ttl_seconds

    @classmethod
    def from_url(cls, url: str, **kwargs) -> RedisCallState:
        # Timeouts: a Redis that hangs must fail a turn in seconds (the caller then hears
        # the fallback line), not hold it forever.
        return cls(redis.Redis.from_url(url, decode_responses=True, socket_timeout=3,
                                        socket_connect_timeout=3), **kwargs)

    # ---------- call lifecycle ----------

    def start_call(self, tenant_id: str, language: str, **meta: Any) -> str:
        call_id = uuid.uuid4().hex
        self.set_state(call_id, _new=True,
                       tenant_id=tenant_id,
                       language=language,
                       **meta,
                       status="active",
                       started_at=datetime.now(UTC).isoformat(),
                       stuck_count=0)
        return call_id

    def end_call(self, call_id: str, outcome: str) -> None:
        self.set_state(call_id, status="ended", outcome=outcome,
                       ended_at=datetime.now(UTC).isoformat())

    def exists(self, call_id: str) -> bool:
        return bool(self.r.exists(_state_key(call_id)))

    # ---------- notebook ----------

    def append(self, call_id: str, message: dict[str, Any]) -> None:
        if message.get("role") not in ROLES:
            raise ValueError(f"role must be one of {sorted(ROLES)}, got {message.get('role')!r}")
        self._require(call_id)
        pipe = self.r.pipeline(transaction=True)
        pipe.rpush(_notebook_key(call_id), json.dumps(message, ensure_ascii=False))
        pipe.expire(_notebook_key(call_id), self.ttl)
        pipe.expire(_state_key(call_id), self.ttl)
        pipe.execute()

    def pop_last(self, call_id: str, role: str) -> dict[str, Any] | None:
        """Remove the newest message if it has this role (e.g. a reply the caller never
        heard because the voice layer dropped the turn). Returns it, or None."""
        self._require(call_id)
        key = _notebook_key(call_id)
        last = self.r.lindex(key, -1)
        if last is None or json.loads(last).get("role") != role:
            return None
        self.r.rpop(key)
        return json.loads(last)

    def messages(self, call_id: str) -> list[dict[str, Any]]:
        self._require(call_id)
        return [json.loads(m) for m in self.r.lrange(_notebook_key(call_id), 0, -1)]

    # ---------- state ----------

    def get_state(self, call_id: str) -> dict[str, Any]:
        raw = self.r.hgetall(_state_key(call_id))
        if not raw:
            raise CallNotFound(call_id)
        return {k: json.loads(v) for k, v in raw.items()}

    def get(self, call_id: str, field: str, default: Any = None) -> Any:
        self._require(call_id)
        value = self.r.hget(_state_key(call_id), field)
        return default if value is None else json.loads(value)

    def set_state(self, call_id: str, _new: bool = False, **fields: Any) -> None:
        if not _new:
            self._require(call_id)
        encoded = {k: json.dumps(v, ensure_ascii=False) for k, v in fields.items()}
        pipe = self.r.pipeline(transaction=True)
        pipe.hset(_state_key(call_id), mapping=encoded)
        pipe.expire(_state_key(call_id), self.ttl)
        pipe.execute()

    def clear(self, call_id: str, *fields: str) -> None:
        self._require(call_id)
        self.r.hdel(_state_key(call_id), *fields)

    def incr(self, call_id: str, field: str, by: int = 1) -> int:
        """Atomic counter (e.g. stuck_count). Stored as a plain integer, which is valid JSON."""
        self._require(call_id)
        return int(self.r.hincrby(_state_key(call_id), field, by))

    def _require(self, call_id: str) -> None:
        if not self.r.exists(_state_key(call_id)):
            raise CallNotFound(call_id)
