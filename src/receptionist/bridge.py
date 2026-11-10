"""The bridge: an OpenAI-compatible server that Bolna uses as its "LLM" (M5).

Bolna sends a chat-completion request every caller turn with the whole transcript.
We take only the caller's latest line, run our CallSession (which keeps the real
conversation in Redis, D33) and stream the reply back as chat-completion chunks.
So Bolna does audio, speech-to-text, text-to-speech and interruptions; our code
decides every word (D42).

Which call?    the request's `user` field = Bolna's run_id (one per call; see the
               fork patch in bolna/llms/openai_llm.py). Mapped to our call_id in
               Redis under bolna:run:{run_id}.
Which business? the request's `model` field = business id (D52).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from receptionist.audit import AuditLog
from receptionist.bookings import BookingStore
from receptionist.business import BusinessRegistry, ConfigError
from receptionist.guard import Guard
from receptionist.model_client import ModelClient, ModelUnavailable
from receptionist.notebook import CallStore
from receptionist.session import CallSession, TurnResult

RUN_TTL = 24 * 60 * 60
CHUNK_CHARS = 40          # stream the reply in ~40-char pieces so speech can start early
DEFAULT_RUN = "unpatched-default"   # used when Bolna sends no `user` (unpatched fork)


class Bridge:
    def __init__(self, registry: BusinessRegistry, calls: CallStore, bookings: BookingStore,
                 audit: AuditLog, model: ModelClient, now=None):
        self.registry = registry
        self.now = now          # clock for the guards; tests pass a fixed one
        self.calls = calls
        self.bookings = bookings
        self.audit = audit
        self.model = model
        self._guards: dict[str, Guard] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def lock_for(self, run_id: str) -> threading.Lock:
        """One turn at a time per call: speech-to-text can split one utterance into
        several fragments that arrive while the previous one is still being answered."""
        with self._locks_guard:
            return self._locks.setdefault(run_id, threading.Lock())

    def guard_for(self, business_id: str) -> Guard:
        if business_id not in self._guards:
            business = self.registry.by_id(business_id)
            self._guards[business_id] = Guard(business, self.bookings, self.calls, self.audit, now=self.now)
        return self._guards[business_id]

    def session_for(self, run_id: str, business_id: str) -> tuple[CallSession, bool]:
        """The CallSession for this Bolna run; started on first sight. Returns (session, new)."""
        guard = self.guard_for(business_id)
        key = f"bolna:run:{run_id}"
        call_id = self.calls.r.get(key)
        if call_id and self.calls.exists(call_id):
            return CallSession(call_id, guard.business, self.calls, guard, self.model), False
        session, _greeting = CallSession.start(guard.business, self.calls, guard, self.model)
        self.calls.r.set(key, session.call_id, ex=RUN_TTL)
        return session, True

    def turn(self, run_id: str, business_id: str, caller_text: str) -> tuple[TurnResult, str]:
        session, new = self.session_for(run_id, business_id)
        started = time.perf_counter()
        result = session.handle(caller_text)
        self.audit.record(call_id=session.call_id, business_id=business_id, action="bridge_turn",
                          args={"run_id": run_id, "new_call": new, "caller": caller_text[:200],
                                "reply": result.reply[:200], "handle_s": round(
                                    time.perf_counter() - started, 3),
                                "model_calls": result.model_calls, "tools": result.tool_calls,
                                "booked": result.booked, "fallback": result.fallback,
                                "replaced": result.replaced_false_claim
                                or result.replaced_unchecked_claim},
                          outcome="ok")
        return result, session.call_id

    def discard_reply(self, call_id: str, business_id: str, reply: str) -> bool:
        """The voice layer dropped this turn (caller spoke again): the caller never heard
        the reply, so it must not stay in the notebook as if they had (D33)."""
        dropped = self.calls.pop_last(call_id, "assistant")
        self.audit.record(call_id=call_id, business_id=business_id, action="reply_discarded_unheard",
                          args={"reply": reply[:200], "removed": dropped is not None}, outcome="ok")
        return dropped is not None

    def skipped_cancelled(self, run_id: str, business_id: str, caller_text: str) -> None:
        self.audit.record(call_id=self.calls.r.get(f"bolna:run:{run_id}"), business_id=business_id,
                          action="turn_skipped_cancelled", args={"caller": caller_text[:200]},
                          outcome="ok")

    def health(self) -> dict[str, Any]:
        started = time.perf_counter()
        reply = self.model.complete([{"role": "user", "content": "Reply with the single word OK."}],
                                    tools=[])
        return {"ok": True, "model_s": round(time.perf_counter() - started, 2),
                "model_reply": (reply.content or "")[:40],
                "businesses": sorted(self.registry._by_id)}


# ---------- OpenAI-compatible HTTP layer ----------

def last_user_text(messages: list[dict]) -> str | None:
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content")
            if isinstance(content, list):   # OpenAI "parts" format
                content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
            return (content or "").strip() or None
    return None


def chunk_text(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Cut at word boundaries into pieces of about `size` characters, spaces kept."""
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
        "id": rid, "object": "chat.completion.chunk", "created": int(time.time()),
        "model": model, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }, ensure_ascii=False) + "\n\n"


def create_app(bridge: Bridge) -> FastAPI:
    app = FastAPI(title="receptionist bridge")

    @app.get("/health")
    async def health():
        try:
            return await run_in_threadpool(bridge.health)
        except (ModelUnavailable, Exception) as e:  # noqa: BLE001 - health must never crash
            return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"[:300]},
                                status_code=503)

    @app.get("/v1/models")
    async def models():
        return {"object": "list", "data": [{"id": b, "object": "model", "owned_by": "receptionist"}
                                           for b in sorted(bridge.registry._by_id)]}

    @app.post("/v1/chat/completions")
    async def completions(request: Request, x_call_id: str | None = Header(default=None)):
        body = await request.json()
        business_id = body.get("model") or ""
        run_id = body.get("user") or x_call_id or DEFAULT_RUN
        messages = body.get("messages") or []
        caller_text = last_user_text(messages)
        if caller_text is None:
            raise HTTPException(400, "no user message in the request")
        try:
            bridge.registry.by_id(business_id)
        except ConfigError:
            raise HTTPException(404, f"unknown business (model) {business_id!r}") from None

        received = time.perf_counter()
        lock = bridge.lock_for(run_id)
        await run_in_threadpool(lock.acquire)
        try:
            if await request.is_disconnected():          # Bolna gave up while we queued
                bridge.skipped_cancelled(run_id, business_id, caller_text)
                print(f"[bridge] {business_id} run={run_id[:8]} skipped (cancelled before start) "
                      f"| {caller_text[:50]!r}", flush=True)
                return JSONResponse({"skipped": "cancelled"}, status_code=499)
            result, call_id = await run_in_threadpool(bridge.turn, run_id, business_id,
                                                      caller_text)
            if await request.is_disconnected():          # answered, but nobody is listening
                bridge.discard_reply(call_id, business_id, result.reply)
                print(f"[bridge] {business_id} run={run_id[:8]} reply discarded (cancelled) "
                      f"| {caller_text[:50]!r}", flush=True)
                return JSONResponse({"skipped": "cancelled_after_reply"}, status_code=499)
        finally:
            lock.release()
        ready_s = time.perf_counter() - received
        rid = "chatcmpl-" + uuid.uuid4().hex[:12]
        print(f"[bridge] {business_id} run={run_id[:8]} call={call_id[:8]} {ready_s:5.2f}s "
              f"model_calls={result.model_calls} tools={'+'.join(result.tool_calls) or '-'} "
              f"{'BOOKED ' if result.booked else ''}{'FALLBACK ' if result.fallback else ''}"
              f"| {caller_text[:50]!r} -> {result.reply[:60]!r}", flush=True)

        if not body.get("stream", False):
            return {"id": rid, "object": "chat.completion", "created": int(time.time()),
                    "model": business_id,
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": result.reply}}],
                    "usage": {"prompt_tokens": result.prompt_tokens,
                              "completion_tokens": 0, "total_tokens": result.prompt_tokens}}

        async def stream():
            yield _chunk(rid, business_id, {"role": "assistant", "content": ""})
            for piece in chunk_text(result.reply):
                yield _chunk(rid, business_id, {"content": piece})
            yield _chunk(rid, business_id, {}, finish="stop")
            yield "data: " + json.dumps({
                "id": rid, "object": "chat.completion.chunk", "created": int(time.time()),
                "model": business_id, "choices": [],
                "usage": {"prompt_tokens": result.prompt_tokens, "completion_tokens": 0,
                          "total_tokens": result.prompt_tokens}}) + "\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Call-Id": call_id})

    return app


def bridge_from_env() -> Bridge:
    """Wire the bridge from environment variables (same defaults as the CLI)."""
    from receptionist.bookings import SqliteBookingStore
    from receptionist.model_client import OpenAICompatibleClient

    registry = BusinessRegistry.from_dir(os.getenv("BUSINESSES_DIR", "businesses"))
    calls = CallStore.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    bookings = SqliteBookingStore(os.getenv("BOOKINGS_DB", "data/bookings.sqlite"))
    audit = AuditLog(os.getenv("AUDIT_LOG", "audit/audit.jsonl"))
    return Bridge(registry, calls, bookings, audit, OpenAICompatibleClient.from_env())
