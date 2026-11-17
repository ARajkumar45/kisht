"""Test chat as a synthetic borrower, from the dashboard. The agent holds nothing between
requests: it is rebuilt from the shared call state every time, so a chat survives a restart
of this process and nothing piles up here."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from kisht.adapters.call_state import CallNotFound
from kisht.agent import Agent
from kisht.api.common import Ctx, refused_as_409
from kisht.wrapup import claim as claim_wrapup


class ChatStart(BaseModel):
    borrower_id: str = Field(min_length=1, max_length=64)
    channel: Literal["chat", "voice"] = "chat"


class ChatSay(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def router(ctx: Ctx) -> APIRouter:
    rt = ctx.rt
    r = APIRouter()

    @r.get("/api/borrowers")
    def borrowers(q: str | None = Query(None, max_length=100),
                  limit: int = Query(60, ge=1, le=200)) -> list[dict[str, Any]]:
        sql = ("SELECT b.id, b.name, b.language, b.city, l.id AS loan_id, l.emi, l.product "
               "FROM borrowers b JOIN loans l ON l.borrower_id = b.id")
        args: list[Any] = []
        if q:
            sql += " WHERE b.name LIKE ? OR b.id LIKE ? OR b.city LIKE ?"
            args = [f"%{q}%"] * 3
        sql += " ORDER BY b.id LIMIT ?"
        return [dict(row) for row in rt.ledger.db.execute(sql, [*args, limit])]

    @r.post("/api/chat/start")
    def chat_start(body: ChatStart) -> dict[str, Any]:
        b = rt.ledger.borrower(body.borrower_id)
        if not b:
            raise HTTPException(404, "no such borrower")
        loans = rt.ledger.loans_for(body.borrower_id)
        if not loans:
            raise HTTPException(404, "this borrower has no loan")
        with refused_as_409():
            agent, greeting = Agent.start(
                guard=rt.guards[b["lender_id"]], calls=rt.calls,
                model=rt.models.for_role("agent"), borrower_id=body.borrower_id,
                loan_id=loans[0]["id"], channel=body.channel,
                agreement=rt.agreements.get(b["lender_id"]), insights=rt.insights,
                source="dashboard")
        return {"call_id": agent.call_id, "greeting": greeting, "borrower": b["name"],
                "language": b["language"]}

    def open_agent(call_id: str) -> Agent:
        try:
            state = rt.calls.get_state(call_id)
        except CallNotFound:
            raise HTTPException(404, "no open chat with this id") from None
        lender_id = state.get("tenant_id")
        if state.get("status") == "ended" or lender_id not in rt.guards:
            raise HTTPException(404, "no open chat with this id")
        return Agent(call_id, rt.guards[lender_id], rt.calls, rt.models.for_role("agent"),
                     rt.agreements.get(lender_id), rt.insights)

    @r.post("/api/chat/{call_id}/say")
    def chat_say(call_id: str, body: ChatSay) -> dict[str, Any]:
        agent = open_agent(call_id)
        with ctx.chat_locks.get(call_id):     # a double send must not run two turns at once
            t = agent.handle(body.text)
        return {"reply": t.reply, "tools": t.tool_calls, "refused": t.refused,
                "replaced": t.replaced, "promise_saved": t.promise_saved, "ended": t.ended,
                "seconds": round(t.model_latency_s, 1)}

    @r.post("/api/chat/{call_id}/end")
    def chat_end(call_id: str) -> dict[str, Any]:
        agent = open_agent(call_id)
        if not claim_wrapup(rt.calls, call_id):      # the sweeper is closing it right now
            raise HTTPException(409, "this chat is already being closed")
        with ctx.chat_locks.get(call_id):
            done = agent.finish()
        ctx.chat_locks.drop(call_id)
        ctx.review_later(call_id, agent.lender)
        return done

    return r
