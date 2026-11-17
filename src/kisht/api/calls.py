"""The call log, one call's full record, the CSV export, and the supervisor's actions on a
call: coach, take over, and a human's own QA marks."""
from __future__ import annotations

import csv
import io
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from kisht.api.common import ALL_ROWS, Ctx, csv_safe, refused_as_409
from kisht.audit import entries_for_call

CSV_COLUMNS = ["call_id", "started_utc", "ended_utc", "borrower_name", "loan_id", "channel",
               "language", "status", "outcome", "turns", "blocks", "reason", "sentiment",
               "qa_score", "source", "note"]
# The ledger tables that carry a call_id, and the name each has in a call's record.
ACTION_TABLES = {"promises": "promises", "links": "payment_links",
                 "escalations": "escalations", "followups": "followups"}


class Coach(BaseModel):
    note: str = Field("", max_length=2000)
    by: str = Field("supervisor", max_length=60)


class HumanQA(BaseModel):
    labels: dict[str, Literal["pass", "fail", "na"]]      # scorecard item id -> result
    by: str = Field("reviewer", max_length=60)


class CallFilters(BaseModel):
    status: str | None = None
    outcome: str | None = None
    language: str | None = None
    flagged: bool = False
    q: str | None = None


def review_with_humans(rt: Any, call_id: str) -> dict[str, Any] | None:
    """The AI review with any human QA marks laid over it; a human mark wins."""
    review = rt.insights.review(call_id)
    if not review:
        return None
    human = {x["item_id"]: x for x in rt.insights.qa_labels(call_id)}
    for q in review["qa"]:
        h = human.get(q["id"])
        q["human"] = {"result": h["result"], "by": h["by"]} if h else None
    final = [(q["human"] or q)["result"] for q in review["qa"]]
    scored = [r for r in final if r != "na"]
    review["human_reviewed"] = bool(human)
    review["final_score"] = (round(100 * scored.count("pass") / len(scored), 1)
                             if scored and human else review["qa_score"])
    return review


def router(ctx: Ctx) -> APIRouter:
    rt = ctx.rt
    r = APIRouter()

    def filtered(f: CallFilters, limit: int = 200) -> list[dict[str, Any]]:
        return rt.insights.calls(status=f.status, outcome=f.outcome, language=f.language,
                                 flagged=f.flagged, q=f.q, limit=limit)

    @r.get("/api/calls")
    def calls(status: str | None = None, outcome: str | None = None,
              language: str | None = None, flagged: bool = False, q: str | None = None
              ) -> list[dict[str, Any]]:
        return filtered(CallFilters(status=status, outcome=outcome, language=language,
                                    flagged=flagged, q=q))

    @r.get("/api/export/calls.csv")
    def calls_csv(status: str | None = None, outcome: str | None = None,
                  language: str | None = None, flagged: bool = False, q: str | None = None
                  ) -> Response:
        rows = filtered(CallFilters(status=status, outcome=outcome, language=language,
                                    flagged=flagged, q=q), limit=ALL_ROWS)
        buf = io.StringIO()
        out = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        out.writeheader()
        out.writerows({k: csv_safe(v) for k, v in row.items()} for row in rows)
        return Response(buf.getvalue(), media_type="text/csv", headers={
            "Content-Disposition": 'attachment; filename="kisht-calls.csv"'})

    def live_guard(call_id: str):
        c = rt.insights.call(call_id)
        if not c:
            raise HTTPException(404, "no such call")
        if c["status"] != "live" or not rt.calls.exists(call_id):
            raise HTTPException(409, "this conversation is no longer live")
        return rt.guards[c["lender_id"]]

    @r.post("/api/calls/{call_id}/coach")
    def coach(call_id: str, body: Coach) -> dict[str, Any]:
        with refused_as_409():
            return live_guard(call_id).coach(call_id, by=body.by, note=body.note)

    @r.post("/api/calls/{call_id}/takeover")
    def takeover(call_id: str, body: Coach) -> dict[str, Any]:
        with refused_as_409():
            return live_guard(call_id).take_over(call_id, by=body.by, note=body.note)

    @r.post("/api/calls/{call_id}/qa")
    def human_qa(call_id: str, body: HumanQA) -> dict[str, Any] | None:
        review = rt.insights.review(call_id)
        if not review:
            raise HTTPException(409, "this call has no review yet")
        known = {q["id"] for q in review["qa"]}
        bad = [k for k in body.labels if k not in known]
        if bad or not body.labels:
            raise HTTPException(400, f"unknown item or result: {', '.join(bad) or 'none given'}")
        rt.insights.set_qa_labels(call_id, body.labels, body.by or "reviewer")
        rt.audit.record(call_id=call_id, tenant_id="qa", action="human_qa_review",
                        args={"by": body.by, "items": len(body.labels)}, outcome="ok")
        return review_with_humans(rt, call_id)

    @r.get("/api/calls/{call_id}")
    def call(call_id: str) -> dict[str, Any]:
        c = rt.insights.call(call_id)
        if not c:
            raise HTTPException(404, "no such call")
        db = rt.ledger.db
        actions = {name: [dict(row) for row in db.execute(
            f"SELECT * FROM {table} WHERE call_id=?", (call_id,))]
            for name, table in ACTION_TABLES.items()}
        return {"call": c, "turns": rt.insights.turns(call_id),
                "spans": rt.insights.spans(call_id),
                "review": review_with_humans(rt, call_id), "actions": actions,
                "audit": entries_for_call(rt.cfg.stores.audit_dir, call_id)
                or [e for e in rt.audit.entries if e["call_id"] == call_id]}

    return r
