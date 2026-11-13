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

A streamed request gets each sentence as soon as the agent has written and checked it, so
Bolna can start speaking after about a second instead of after the whole reply (D108).
"""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import os
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
from kisht.agent import Agent, TurnResult, prepare
from kisht.guard import GuardRefused, PolicyGuard
from kisht.insights import InsightsStore
from kisht.knowledge import Agreement
from kisht.languages import say
from kisht.lender import ConfigError, LenderRegistry
from kisht.ports import ChatModel
from kisht.wrapup import finish_in_background

log = logging.getLogger("kisht.bridge")

RUN_TTL = 24 * 60 * 60
LOCK_WAIT_S = 30                    # a new utterance never waits longer for the turn before it
MAX_TEXT = 2000                     # characters of one utterance; more is not speech
TOKEN_ENV = "KISHT_BRIDGE_TOKEN"    # if set, every request must carry it as a bearer token


class _CallerGone(Exception):
    """The voice layer dropped this turn (the caller spoke over us): stop working on it."""
CHUNK_CHARS = 40
DEFAULT_RUN = "unpatched-default"


class VoiceBridge:
    def __init__(self, *, lenders: LenderRegistry, guards: dict[str, PolicyGuard],
                 calls: RedisCallState, model: ChatModel,
                 agreements: dict[str, Agreement] | None = None,
                 insights: InsightsStore | None = None,
                 reviewer_model: ChatModel | None = None):
        self.lenders = lenders
        self.insights = insights
        self.reviewer_model = reviewer_model
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
            state = self.calls.get_state(call_id)
            # Reuse the conversation only if it is this borrower's and still open. Without
            # this, a client that sends no run id (unpatched Bolna: every call is
            # "unpatched-default") continued the previous borrower's verified conversation.
            if state.get("borrower_id") == borrower_id and state.get("status") != "ended":
                return (Agent(call_id, guard, self.calls, self.model, agreement, self.insights),
                        False, None)
        loans = guard.ledger.loans_for(borrower_id)
        if not loans:
            raise ConfigError(f"no loan for borrower {borrower_id!r}")
        try:
            agent, _greeting = Agent.start(guard=guard, calls=self.calls, model=self.model,
                                           borrower_id=borrower_id, loan_id=loans[0]["id"],
                                           channel="voice", agreement=agreement,
                                           insights=self.insights, warm=False)
        except GuardRefused as e:
            lang = (guard.ledger.borrower(borrower_id) or {}).get("language", "en")
            guard.audit.record(call_id=None, tenant_id=lender_id, action="voice_refused",
                               args={"run_id": run_id}, outcome="denied",
                               detail=f"{e.code}: {e.message}")
            return None, True, say(lang, "not_now")
        self.calls.r.set(key, agent.call_id, ex=RUN_TTL)
        return agent, True, None

    def turn(self, run_id: str, target: str, text: str,
             on_say: Any = None) -> tuple[TurnResult, str | None]:
        agent, new, refusal = self.agent_for(run_id, target)
        if agent is None:
            if on_say and refusal:
                on_say(refusal)
            return TurnResult(reply=refusal or "", ended="refused"), None
        try:
            result = agent.handle(text, on_say=on_say)
        except _CallerGone:
            raise
        except Exception:
            # Redis hiccup, a locked database, a bug: the caller must still hear something,
            # and the reason must be findable afterwards.
            log.exception("voice turn failed (call %s)", agent.call_id)
            line = say(agent.lender.languages.default, "fallback")
            with contextlib.suppress(Exception):   # needs the store that may have just failed
                line = agent.say("fallback")
            if on_say:
                on_say(line)
            return TurnResult(reply=line, fallback=True), agent.call_id
        if result.ended:
            # In the background: the caller hears the last reply now, not after the case note.
            finish_in_background(agent, self.reviewer_model)
            with self._locks_guard:
                self._locks.pop(run_id, None)       # the call is over: do not keep its lock
        agent.guard.audit.record(call_id=agent.call_id, tenant_id=agent.lender.id,
                                 action="voice_turn", outcome="ok",
                                 args={"run_id": run_id, "new_call": new, "tools": result.tool_calls,
                                       "refused": result.refused, "replaced": result.replaced,
                                       "seconds": round(result.model_latency_s, 2),
                                       "first_words_s": (round(result.first_say_s, 2)
                                                         if result.first_say_s is not None
                                                         else None)})
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

    token = os.environ.get(TOKEN_ENV, "")

    def authorise(request: Request) -> None:
        """With KISHT_BRIDGE_TOKEN set (do this before opening a tunnel), every request must
        carry it; the voice layer sends it as its LLM API key."""
        if token and not hmac.compare_digest(
                request.headers.get("authorization", ""), f"Bearer {token}"):
            raise HTTPException(401, "missing or wrong bearer token")

    async def json_object(request: Request) -> dict:
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, "the body must be JSON") from None
        if not isinstance(body, dict):
            raise HTTPException(400, "the body must be a JSON object")
        return body

    @app.get("/health")
    async def health(deep: bool = False) -> Any:
        """Cheap by default (a monitor may ask often, and a real completion would take a model
        slot from a live call): the model server answers and Redis answers. ?deep=1 runs a
        real completion, the only proof the model can generate."""
        if deep:
            r = await run_in_threadpool(health_check, bridge.model)
            return JSONResponse(r, status_code=200 if r["ok"] else 503)

        def cheap() -> dict[str, bool]:
            try:
                redis_ok = bool(bridge.calls.r.ping())
            except Exception:  # noqa: BLE001 - any failure means "down"
                redis_ok = False
            reach = getattr(bridge.model, "reachable", None)
            return {"call_state": redis_ok, "model": bool(reach()) if reach else True}

        r = await run_in_threadpool(cheap)
        return JSONResponse({"ok": all(r.values()), **r}, status_code=200 if all(r.values()) else 503)

    @app.post("/prepare")
    async def prepare_call(request: Request) -> Any:
        """Call this when the phone starts ringing: {"model": "<lender_id>:<borrower_id>"}.
        The model server reads that borrower's instructions meanwhile (about 5 s), so the
        first reply of the call does not wait for it."""
        authorise(request)
        body = await json_object(request)
        try:
            lender_id, borrower_id = bridge.parse_target(str(body.get("model") or ""))
            bridge.lenders.get(lender_id)
        except ConfigError as e:
            raise HTTPException(404, str(e)) from None
        ok = await run_in_threadpool(prepare, bridge.model, bridge.guards[lender_id], borrower_id)
        if not ok:
            raise HTTPException(404, f"nothing to prepare for {borrower_id!r}")
        return {"preparing": True}

    @app.post("/v1/chat/completions")
    async def completions(request: Request):
        authorise(request)
        body = await json_object(request)
        target = str(body.get("model") or "")
        run_id = str(body.get("user") or DEFAULT_RUN)[:200]
        messages = body.get("messages")
        if not isinstance(messages, list):
            raise HTTPException(400, "messages must be a list")
        text = last_user_text([m for m in messages if isinstance(m, dict)])
        if text is None:
            raise HTTPException(400, "no user message in the request")
        text = text[:MAX_TEXT]
        try:
            lender_id, _ = bridge.parse_target(target)
            bridge.lenders.get(lender_id)
        except ConfigError as e:
            raise HTTPException(404, str(e)) from None
        lock = bridge.lock_for(run_id)
        rid = "chatcmpl-" + uuid.uuid4().hex[:12]
        if not await run_in_threadpool(lock.acquire, True, LOCK_WAIT_S):
            raise HTTPException(503, "the previous turn of this call is still running")
        if await request.is_disconnected():
            lock.release()
            return JSONResponse({"skipped": "cancelled"}, status_code=499)

        if not body.get("stream", False):
            try:
                try:
                    result, call_id = await run_in_threadpool(bridge.turn, run_id, target, text)
                except ConfigError as e:
                    raise HTTPException(404, str(e)) from None
                if call_id and await request.is_disconnected():
                    bridge.discard_reply(call_id)
                    return JSONResponse({"skipped": "cancelled_after_reply"}, status_code=499)
            finally:
                lock.release()
            return {"id": rid, "object": "chat.completion", "created": int(time.time()),
                    "model": target, "choices": [{"index": 0, "finish_reason": "stop",
                                                  "message": {"role": "assistant",
                                                              "content": result.reply}}]}

        # Streamed: the turn runs in its own thread and hands over each sentence when it is
        # ready. Until the first one arrives nothing has been sent, so an unknown borrower can
        # still be answered with a 404.
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        state = {"gone": False}

        def hand_over(piece: str) -> None:
            if state["gone"]:
                raise _CallerGone       # stops the model call in flight; nobody is listening
            loop.call_soon_threadsafe(queue.put_nowait, piece)

        def work() -> None:
            try:
                _, call_id = bridge.turn(run_id, target, text, on_say=hand_over)
                if call_id and state["gone"]:
                    bridge.discard_reply(call_id)     # the caller never heard all of it
            except _CallerGone:
                pass                                  # no reply was saved for this turn
            except Exception as e:
                if not isinstance(e, ConfigError):
                    log.exception("voice turn failed before it started (run %s)", run_id)
                loop.call_soon_threadsafe(queue.put_nowait, e)
            finally:
                lock.release()
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=work, daemon=True).start()
        first = await queue.get()
        if isinstance(first, ConfigError):
            raise HTTPException(404, str(first)) from None
        if isinstance(first, Exception):
            raise HTTPException(500, "turn failed") from first

        async def stream():
            try:
                yield _chunk(rid, target, {"role": "assistant", "content": ""})
                item, sent = first, False
                while item is not None and not isinstance(item, Exception):
                    for piece in chunk_text((" " if sent else "") + item):
                        yield _chunk(rid, target, {"content": piece})
                    sent = True
                    item = await queue.get()
                yield _chunk(rid, target, {}, finish="stop")
                yield "data: [DONE]\n\n"
            finally:
                # Reached early when Bolna drops the request (the caller spoke over us).
                state["gone"] = item is not None

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    return app
