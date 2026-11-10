"""Voice channel: an OpenAI-compatible endpoint that the Bolna voice framework uses as its
"LLM". Bolna handles audio, speech-to-text (Sarvam), text-to-speech and barge-in; every word
the caller hears still comes from our Agent, guard and checks.

Which conversation?  the request's `user` field = Bolna's run_id (one per call; fork patch in
                     bolna/llms/openai_llm.py), mapped to our call id in Redis.
Which account?       the request's `model` field = "<lender_id>:<borrower_id>", set in the Bolna
                     agent config (tools/make_voice_agent.py), whose welcome message is our
                     greeting for that borrower.
We take only the caller's latest line from Bolna's history: our transcript is the source of
truth. One turn at a time per call; a turn Bolna cancelled is skipped; a reply the caller never
heard is removed from the transcript (M5, D83).
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from kisht.adapters.call_state import RedisCallState
from kisht.adapters.llm import health_check
from kisht.agent import Agent, TurnResult
from kisht.guard import GuardRefused, PolicyGuard
from kisht.knowledge import Agreement
from kisht.lender import ConfigError, LenderRegistry
from kisht.ports import ChatModel

RUN_TTL = 24 * 60 * 60
CHUNK_CHARS = 40
DEFAULT_RUN = "unpatched-default"
NOT_NOW = {"en": "Sorry, we cannot discuss this right now. Thank you, goodbye.",
           "hi": "Maaf kijiye, abhi baat nahi ho sakti. Dhanyavaad."}


class VoiceBridge:
    def __init__(self, *, lenders: LenderRegistry, guards: dict[str, PolicyGuard],
                 calls: RedisCallState, model: ChatModel,
                 agreements: dict[str, Agreement] | None = None):
        self.lenders = lenders
        self.guards = guards
        self.calls = calls
        self.model = model
        self.agreements = agreements or {}
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def lock_for(self, run_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(run_id, threading.Lock())

    @staticmethod
    def parse_target(model_field: str) -> tuple[str, str]:
        lender_id, _, borrower_id = (model_field or "").partition(":")
        if not lender_id or not borrower_id:
            raise ConfigError("model must be '<lender_id>:<borrower_id>'")
        return lender_id, borrower_id

    def agent_for(self, run_id: str, target: str) -> tuple[Agent | None, bool, str | None]:
        """(agent, is_new, refusal_reply). Starts the conversation on first sight."""
        lender_id, borrower_id = self.parse_target(target)
        guard = self.guards[lender_id]
        key = f"bolna:run:{run_id}"
        call_id = self.calls.r.get(key)
        agreement = self.agreements.get(lender_id)
        if call_id and self.calls.exists(call_id):
            return Agent(call_id, guard, self.calls, self.model, agreement), False, None
        loans = guard.ledger.loans_for(borrower_id)
        if not loans:
            raise ConfigError(f"no loan for borrower {borrower_id!r}")
        try:
            agent, _greeting = Agent.start(guard=guard, calls=self.calls, model=self.model,
                                           borrower_id=borrower_id, loan_id=loans[0]["id"],
                                           channel="voice", agreement=agreement)
        except GuardRefused as e:
            lang = (guard.ledger.borrower(borrower_id) or {}).get("language", "en")
            guard.audit.record(call_id=None, tenant_id=lender_id, action="voice_refused",
                               args={"run_id": run_id}, outcome="denied",
                               detail=f"{e.code}: {e.message}")
            return None, True, NOT_NOW.get(lang, NOT_NOW["en"])
        self.calls.r.set(key, agent.call_id, ex=RUN_TTL)
        return agent, True, None

    def turn(self, run_id: str, target: str, text: str) -> tuple[TurnResult, str | None]:
        agent, new, refusal = self.agent_for(run_id, target)
        if agent is None:
            return TurnResult(reply=refusal or "", ended="refused"), None
        result = agent.handle(text)
        if result.ended:
            agent.finish()
        agent.guard.audit.record(call_id=agent.call_id, tenant_id=agent.lender.id,
                                 action="voice_turn", outcome="ok",
                                 args={"run_id": run_id, "new_call": new, "tools": result.tool_calls,
                                       "refused": result.refused, "replaced": result.replaced,
                                       "seconds": round(result.model_latency_s, 2)})
        return result, agent.call_id

    def discard_reply(self, call_id: str) -> bool:
        return self.calls.pop_last(call_id, "assistant") is not None


def last_user_text(messages: list[dict]) -> str | None:
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content")
            if isinstance(content, list):
                content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
            return (content or "").strip() or None
    return None


def chunk_text(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Word-boundary pieces of about `size` characters, so speech can start early."""
    pieces, buf = [], ""
    for word in re.split(r"(\s+)", text):
        buf += word
        if len(buf) >= size and not word.isspace():
            pieces.append(buf)
            buf = ""
    if buf:
        pieces.append(buf)
    return pieces


def _chunk(rid: str, model: str, delta: dict, finish: str | None = None) -> str:
    return "data: " + json.dumps({
        "id": rid, "object": "chat.completion.chunk", "created": int(time.time()), "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]},
        ensure_ascii=False) + "\n\n"


def create_app(bridge: VoiceBridge) -> FastAPI:
    app = FastAPI(title="kisht voice bridge")

    @app.get("/health")
    async def health() -> Any:
        r = await run_in_threadpool(health_check, bridge.model)
        return JSONResponse(r, status_code=200 if r["ok"] else 503)

    @app.post("/v1/chat/completions")
    async def completions(request: Request):
        body = await request.json()
        target = body.get("model") or ""
        run_id = body.get("user") or DEFAULT_RUN
        text = last_user_text(body.get("messages") or [])
        if text is None:
            raise HTTPException(400, "no user message in the request")
        try:
            lender_id, _ = bridge.parse_target(target)
            bridge.lenders.get(lender_id)
        except ConfigError as e:
            raise HTTPException(404, str(e)) from None
        lock = bridge.lock_for(run_id)
        await run_in_threadpool(lock.acquire)
        try:
            if await request.is_disconnected():
                return JSONResponse({"skipped": "cancelled"}, status_code=499)
            try:
                result, call_id = await run_in_threadpool(bridge.turn, run_id, target, text)
            except ConfigError as e:
                raise HTTPException(404, str(e)) from None
            if call_id and await request.is_disconnected():
                bridge.discard_reply(call_id)
                return JSONResponse({"skipped": "cancelled_after_reply"}, status_code=499)
        finally:
            lock.release()
        rid = "chatcmpl-" + uuid.uuid4().hex[:12]
        if not body.get("stream", False):
            return {"id": rid, "object": "chat.completion", "created": int(time.time()),
                    "model": target, "choices": [{"index": 0, "finish_reason": "stop",
                                                  "message": {"role": "assistant",
                                                              "content": result.reply}}]}

        async def stream():
            yield _chunk(rid, target, {"role": "assistant", "content": ""})
            for piece in chunk_text(result.reply):
                yield _chunk(rid, target, {"content": piece})
            yield _chunk(rid, target, {}, finish="stop")
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    return app
