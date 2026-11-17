"""The human desk: escalated cases routed to teams with a deadline, and agent assist (a brief,
the next best action and suggested replies; answers from the loan agreement)."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from kisht.api.common import Ctx, json_from

DESK_LIMIT = 500


class DeskUpdate(BaseModel):
    status: Literal["open", "in_progress", "resolved"] | None = None
    assignee: str | None = Field(None, max_length=80)
    resolution: str | None = Field(None, max_length=2000)


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    lender_id: str = "demo-nbfc"


def router(ctx: Ctx) -> APIRouter:
    rt = ctx.rt
    r = APIRouter()

    def desk_item(e: dict) -> dict[str, Any]:
        loan = rt.ledger.loan(e["loan_id"])
        b = rt.ledger.borrower(loan["borrower_id"])
        lender = rt.lenders.get(loan["lender_id"])
        state = rt.insights.desk_state(e["id"]) or {}
        review = rt.insights.review(e["call_id"]) if e.get("call_id") else None
        status = state.get("status") or "open"
        # The clock stops when the case is resolved.
        until = (datetime.fromisoformat(state["updated_utc"]) if status == "resolved"
                 else datetime.now(UTC))
        age_h = (until - datetime.fromisoformat(e["created_utc"])).total_seconds() / 3600
        sla_h = lender.sla_hours_for(e["reason"])
        return {**e, "borrower_id": b["id"], "borrower_name": b["name"],
                "age_hours": round(age_h, 1), "sla_hours": sla_h, "breached": age_h > sla_h,
                "language": b["language"], "city": b["city"], "emi": loan["emi"],
                "team": state.get("team") or lender.team_for(e["reason"]),
                "status": status, "assignee": state.get("assignee"),
                "resolution": state.get("resolution"),
                "review": {"summary": review["summary"], "sentiment": review["sentiment"]}
                if review else None}

    def escalation(eid: str) -> dict[str, Any]:
        row = rt.ledger.db.execute("SELECT * FROM escalations WHERE id=?", (eid,)).fetchone()
        if not row:
            raise HTTPException(404, "no such escalation")
        return desk_item(dict(row))

    @r.get("/api/desk")
    def desk() -> list[dict[str, Any]]:
        rows = rt.ledger.db.execute("SELECT * FROM escalations ORDER BY created_utc DESC "
                                    "LIMIT ?", (DESK_LIMIT,)).fetchall()
        items = [desk_item(dict(row)) for row in rows]
        # Unresolved first; within those, the case closest to (or furthest past) its deadline.
        items.sort(key=lambda d: (d["status"] == "resolved", d["sla_hours"] - d["age_hours"]))
        return items

    @r.post("/api/desk/{eid}")
    def desk_update(eid: str, body: DeskUpdate) -> dict[str, Any]:
        item = escalation(eid)
        status = body.status or item["status"]
        # The ledger row is what the guard reads for the contact hold (R1): keep it in step,
        # or a resolved case would block agent contact with this borrower for ever.
        if status == "resolved":
            rt.ledger.resolve_escalation(eid)
        else:
            rt.ledger.reopen_escalation(eid)
        assignee = body.assignee or item["assignee"]
        rt.insights.set_desk(eid, team=item["team"], status=status, assignee=assignee,
                             resolution=body.resolution or item["resolution"])
        if status == "resolved" and item["status"] != "resolved" and body.resolution:
            # Close the loop: the agent reads this the next time it talks to the borrower.
            loan = rt.ledger.loan(item["loan_id"])
            rt.ledger.add_desk_note(
                lender_id=loan["lender_id"], borrower_id=item["borrower_id"],
                loan_id=item["loan_id"],
                note=f"Human desk ({assignee or item['team']}) resolved the {item['reason']} "
                     f"case: {body.resolution}")
        rt.audit.record(call_id=item.get("call_id"), tenant_id="desk", action="desk_update",
                        args={"escalation_id": eid, "status": status,
                              "assignee": body.assignee}, outcome="ok")
        return escalation(eid)

    @r.post("/api/desk/{eid}/assist")
    def assist(eid: str) -> dict[str, Any]:
        item = escalation(eid)
        loan = rt.ledger.loan(item["loan_id"])
        lender = rt.lenders.get(loan["lender_id"])
        dues = rt.ledger.dues(item["loan_id"], rt.guards[lender.id].today()).as_dict()
        turns = rt.insights.turns(item["call_id"]) if item.get("call_id") else []
        notes = rt.ledger.recent_notes(item["borrower_id"])
        model = rt.models.for_role("reviewer")
        reply = model.complete([{"role": "user",
                                 "content": assist_prompt(item, lender, dues, notes, turns)}])
        data = json_from(reply.content) or {"brief": reply.content[:400]}
        return {**data, "dues": dues, "notes": notes, "model": model.name}

    @r.post("/api/assist/ask")
    def ask(body: Ask) -> dict[str, Any]:
        agreement = rt.agreements.get(body.lender_id)
        if not agreement:
            raise HTTPException(404, "no agreement for this lender")
        sections = agreement.search(body.question, k=3)
        if not sections:
            return {"answer": "The agreement does not cover this.", "sections": []}
        context = "\n\n".join(f"[Section {s.id}: {s.title}] {s.text}" for s in sections)
        reply = rt.models.for_role("reviewer").complete([{"role": "user", "content": (
            "Answer the question from these loan agreement sections only, in two or three "
            "sentences, and cite the section numbers like (Section 4).\n\n" + context +
            "\n\nQUESTION: " + body.question)}])
        return {"answer": reply.content.strip(),
                "sections": [{"id": s.id, "title": s.title, "text": s.text} for s in sections]}

    return r


def assist_prompt(item: dict, lender: Any, dues: dict, notes: list[dict],
                  turns: list[dict]) -> str:
    convo = "\n".join(f"Borrower: {t['borrower']}\nAgent: {t['agent']}" if t["borrower"]
                      else f"Agent: {t['agent']}" for t in turns)
    past = "; ".join(n["note"] or "" for n in notes)
    return (
        f"You assist a human agent at a loan company's {item['team']}. The AI agent handed "
        "this case over. Help the human handle the call back well and within policy.\n\n"
        f"CASE: reason {item['reason']}; AI summary: {item['summary']}\n"
        f"DUES: {json.dumps(dues)}\nPOLICY: promises at most "
        f"{lender.promises.max_days_after_due} days after due; part payment at least "
        f"{lender.promises.min_part_payment_pct}%; waivers, settlements and restructuring "
        f"need a manager's approval.\nPAST NOTES: {past}\n\nCONVERSATION:\n{convo}"
        "\n\nAnswer with ONLY JSON: {\"brief\": two sentences on the situation, "
        "\"next_best_action\": one sentence, \"suggested_replies\": [three short things the "
        "human could say, in the borrower's language], \"watch_out\": one sentence on "
        "risk or compliance}")
