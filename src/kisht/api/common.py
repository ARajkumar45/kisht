"""What every route module shares: paths, small helpers, a cache, background work, per-chat
locks, and the context object each router is built from. Nothing here knows about a route."""
from __future__ import annotations

import contextlib
import json
import os
import re
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from fastapi import HTTPException

from kisht.guard import GuardRefused
from kisht.keyed_locks import KeyedLocks
from kisht.runtime import Runtime

# Run from the repo root (like every kisht command: config.yaml is relative). In Docker the
# package lives in the venv, so paths come from the working directory, not from __file__.
ROOT = Path(os.environ.get("KISHT_ROOT", "."))
DIST = ROOT / "dashboard" / "dist"
SHUTDOWN_WAIT_S = 20.0
ALL_ROWS = 10_000                       # "every call" for the KPI pages; the log pages page
_FORMULA = ("=", "+", "-", "@", "\t", "\r")

T = TypeVar("T")


def pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


def json_from(text: str) -> dict | None:
    """The first {...} in a model reply, or None. Models wrap JSON in prose and fences."""
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    try:
        value = json.loads(m.group()) if m else None
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def csv_safe(value: Any) -> Any:
    """A cell that starts with = + - @ runs as a formula when the file is opened in a
    spreadsheet (a borrower's name or a note can carry one). A leading ' makes it text."""
    return "'" + value if isinstance(value, str) and value.startswith(_FORMULA) else value


@contextlib.contextmanager
def refused_as_409() -> Iterator[None]:
    """A guard refusal is the borrower's case saying no, not a server error."""
    try:
        yield
    except GuardRefused as e:
        raise HTTPException(409, f"{e.code}: {e.message}") from e


class TTLCache:
    """One value, recomputed at most once per `seconds`. The lock means a burst of dashboard
    polls computes it once instead of once per request."""

    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic):
        self.seconds, self._clock = seconds, clock
        self._lock = threading.Lock()
        self._at = 0.0
        self._value: Any = None
        self._fresh = False

    def get(self, compute: Callable[[], T]) -> T:
        with self._lock:
            if not (self._fresh and self._clock() - self._at < self.seconds):
                self._value, self._at, self._fresh = compute(), self._clock(), True
            return self._value


class Background:
    """Work that must not hold up a reply (the post-call review). On a normal stop it gets up
    to SHUTDOWN_WAIT_S to finish, so a deploy does not leave a review half-written."""

    def __init__(self) -> None:
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()

    def run(self, fn: Callable[[], None]) -> None:
        t = threading.Thread(target=fn, daemon=True)
        with self._lock:
            self._threads = [x for x in self._threads if x.is_alive()] + [t]
        t.start()

    def join(self, timeout_s: float = SHUTDOWN_WAIT_S) -> None:
        deadline = time.monotonic() + timeout_s
        with self._lock:
            threads = list(self._threads)
        for t in threads:
            t.join(max(0.0, deadline - time.monotonic()))


@dataclass
class Ctx:
    """What a router needs. Built once per app; routers hold no other state."""
    rt: Runtime
    tokens: dict[str, str] = field(default_factory=dict)
    background: Background = field(default_factory=Background)
    chat_locks: KeyedLocks = field(default_factory=KeyedLocks)

    def review_later(self, call_id: str, lender: Any) -> None:
        from kisht.review import Reviewer

        rt = self.rt
        self.background.run(
            lambda: Reviewer(rt.models.for_role("reviewer"), rt.insights).review(call_id, lender))
