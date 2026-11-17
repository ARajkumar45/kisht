"""Supervisor view: conversations happening now, and the alerts behind them."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from kisht.api.common import Ctx

LIVE_LIMIT = 50          # live conversations shown
ALERT_CALLS = 40         # recent calls scanned for alerts
ALERT_LIMIT = 50
STALE_MINUTES = 120


def router(ctx: Ctx) -> APIRouter:
    rt = ctx.rt
    r = APIRouter()

    @r.get("/api/live")
    def live() -> dict[str, Any]:
        # Safety net only, and late: the sweeper wraps a quiet call up properly after 30
        # minutes (case note, ledger contact, review). At 30 here, this poll won that race
        # and the call got none of those.
        rt.insights.close_stale(max_idle_minutes=STALE_MINUTES)
        live_calls = [{**c, "last_turns": rt.insights.turns(c["call_id"])[-4:]}
                      for c in rt.insights.calls(status="live", limit=LIVE_LIMIT)]
        recent = rt.insights.calls(limit=ALERT_CALLS)
        names = {c["call_id"]: c["borrower_name"] for c in recent}
        alerts = [{"call_id": t["call_id"], "at": t["at_utc"],
                   "borrower_name": names[t["call_id"]], "kind": kind,
                   "said": (t["agent"] or "")[:160]}
                  for t in rt.insights.flagged_turns(list(names))
                  for kind in (t["replaced"] or []) + (t["refused"] or [])]
        alerts += [{"call_id": c["call_id"], "at": c["ended_utc"],
                    "borrower_name": c["borrower_name"], "kind": c["outcome"],
                    "said": c["note"] or ""}
                   for c in recent if (c["outcome"] or "").startswith("escalated:")]
        alerts.sort(key=lambda a: a["at"] or "", reverse=True)
        return {"live": live_calls, "alerts": alerts[:ALERT_LIMIT]}

    return r
