"""Who am I, is everything up, which rules are enforced where, and today's plan."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from typing import Any

import httpx
from fastapi import APIRouter, Request

from kisht import compliance
from kisht.api.auth import role_of
from kisht.api.common import ALL_ROWS, ROOT, Ctx, TTLCache

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def router(ctx: Ctx) -> APIRouter:
    rt = ctx.rt
    r = APIRouter()
    rules_cache, health_cache = TTLCache(30), TTLCache(5)

    @r.get("/api/me")
    def me(request: Request) -> dict[str, Any]:
        """Who the dashboard is signed in as."""
        return {"login": bool(ctx.tokens), "role": role_of(request), "mode": rt.cfg.mode}

    @r.get("/api/compliance")
    def rules() -> dict[str, Any]:
        """The rules-to-code table plus how often each rule actually stopped something.
        Cached for 30 s: counting reads every audit file."""
        def compute() -> dict[str, Any]:
            book = compliance.load(ROOT / "compliance" / "rbi-recovery-2027.yaml")
            counts = compliance.blocked_counts(ROOT / rt.cfg.stores.audit_dir, rt.insights)
            return compliance.as_dict(book, counts)
        return rules_cache.get(compute)

    @r.get("/api/health")
    def health() -> dict[str, Any]:
        """Cheap and cached for 5 s: the dashboard asks every few seconds. The model check
        only says the server answers; `kisht health` runs a real completion."""
        return health_cache.get(lambda: _health(rt))

    @r.get("/api/plan")
    def plan(day: str | None = None) -> dict[str, Any]:
        day = day or rt.ledger.db.execute("SELECT MAX(plan_date) FROM plans").fetchone()[0]
        if not day:
            return {"date": None, "items": []}
        on = date.fromisoformat(day)
        rows = rt.ledger.db.execute(
            "SELECT p.*, l.borrower_id, l.emi, b.name, b.language, b.city FROM plans p "
            "JOIN loans l ON l.id = p.loan_id JOIN borrowers b ON b.id = l.borrower_id "
            "WHERE p.plan_date=?", (day,)).fetchall()
        # Newest call per loan wins: calls() is newest first, so walk it oldest first.
        contacted = {c["loan_id"]: c for c in reversed(rt.insights.calls(limit=ALL_ROWS))}
        items = []
        for row in rows:
            d = rt.ledger.dues(row["loan_id"], on)
            c = contacted.get(row["loan_id"])
            items.append({**dict(row), "days_past_due": d.days_past_due,
                          "overdue_amount": d.overdue_amount,
                          "call_id": c["call_id"] if c else None,
                          "outcome": c["outcome"] if c else None})
        items.sort(key=lambda x: (PRIORITY_ORDER.get(x["priority"], 3), -x["days_past_due"]))
        return {"date": day, "items": items,
                "counts": dict(Counter(i["priority"] for i in items))}

    return r


def _health(rt: Any) -> dict[str, Any]:
    role = rt.cfg.llm_roles["agent"]
    server = rt.cfg.llm_servers[role.server]
    try:
        model_ok = httpx.get(server.base_url.rstrip("/") + "/models", timeout=1.5).is_success
    except httpx.HTTPError:
        model_ok = False
    try:
        redis_ok = bool(rt.calls.r.ping())
    except Exception:  # noqa: BLE001 - any failure means "down"
        redis_ok = False
    guard = next(iter(rt.guards.values()))
    now = guard.now()
    window = guard.lender.contact.window
    return {"mode": rt.cfg.mode,
            "model": {"ok": model_ok, "name": role.model.split("/")[-1], "server": role.server},
            "call_state": {"ok": redis_ok},
            "clock": {"now": now.isoformat(timespec="minutes"),
                      "fixed": abs((now - datetime.now(now.tzinfo)).total_seconds()) > 120,
                      "window": f"{window.start:%H:%M}-{window.end:%H:%M}",
                      "open": window.start <= now.time() < window.end}}
