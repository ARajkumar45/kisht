"""Per-key locks with a bound, for per-conversation turn ordering."""
from __future__ import annotations

import threading


class KeyedLocks:
    """One lock per conversation, so two requests for the same conversation cannot run two
    turns at once. A conversation that ends without saying so would leave its lock behind:
    past `limit` entries, locks nobody holds are dropped."""

    def __init__(self, limit: int = 1000) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()
        self.limit = limit

    def get(self, key: str) -> threading.Lock:
        with self._lock:
            if len(self._locks) >= self.limit:
                self._locks = {k: v for k, v in self._locks.items() if v.locked()}
            return self._locks.setdefault(key, threading.Lock())

    def drop(self, key: str) -> None:
        with self._lock:
            self._locks.pop(key, None)

    def __len__(self) -> int:
        return len(self._locks)
