"""Closing conversations properly, whoever ended them.

A chat ends when someone presses End; a phone call just goes quiet. Either way the call needs
the same wrap-up: a case note for next time, the ledger contact closed, and a post-call review.
finish_and_review does that for one conversation. sweep finds live conversations that have
been silent too long (a hung-up call, a closed browser tab) and wraps them up; a conversation
whose state has already expired is marked abandoned. A Redis lock makes sure two processes
(the voice bridge and the dashboard) never wrap up the same call twice.
"""
from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

from kisht.agent import Agent
from kisht.insights import InsightsStore
from kisht.ports import ChatModel
from kisht.review import Reviewer

VOICE_IDLE_S = 300        # a turn can take a minute when the model server is busy
CHAT_IDLE_S = 30 * 60
LOCK_TTL_S = 600


def _claim(calls: Any, call_id: str) -> bool:
    return bool(calls.r.set(f"wrapup:{call_id}", "1", nx=True, ex=LOCK_TTL_S))


def finish_and_review(agent: Agent, reviewer_model: ChatModel | None) -> dict[str, str] | None:
    """Case note + close + review, once. Returns None if another process already did it."""
    if not _claim(agent.calls, agent.call_id):
        return None
    done = agent.finish()
    if agent.insights and reviewer_model:
        Reviewer(reviewer_model, agent.insights).review(agent.call_id, agent.lender)
    return done


def finish_in_background(agent: Agent, reviewer_model: ChatModel | None) -> None:
    """For the voice path: the caller must hear the last reply now, not after the case note."""
    threading.Thread(target=finish_and_review, args=(agent, reviewer_model), daemon=True).start()


def sweep(*, insights: InsightsStore, calls: Any, guards: dict, agent_model: ChatModel,
          reviewer_model: ChatModel | None, agreements: dict | None = None,
          voice_idle_s: int = VOICE_IDLE_S, chat_idle_s: int = CHAT_IDLE_S) -> int:
    """Wrap up live conversations that have gone quiet. Returns how many were closed."""
    now = datetime.now(UTC)
    closed = 0
    for c in insights.live_with_last_activity():
        idle = (now - datetime.fromisoformat(c["last_at"])).total_seconds()
        if idle < (voice_idle_s if c["channel"] == "voice" else chat_idle_s):
            continue
        guard = guards.get(c["lender_id"])
        if guard is None or not calls.exists(c["call_id"]):
            closed += insights.close_abandoned(c["call_id"])
            continue
        agent = Agent(c["call_id"], guard, calls, agent_model,
                      (agreements or {}).get(c["lender_id"]), insights)
        if finish_and_review(agent, reviewer_model):
            closed += 1
    return closed


def start_sweeper(interval_s: int = 30, **kw: Any) -> threading.Thread:
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(interval_s):
            try:
                sweep(**kw)
            except Exception:  # noqa: BLE001, S112 - the sweeper must survive any one bad call
                continue

    t = threading.Thread(target=loop, daemon=True, name="kisht-sweeper")
    t.stop = stop  # type: ignore[attr-defined]
    t.start()
    return t
