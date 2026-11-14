"""The contact-centre API behind the dashboard. Everything here reads the same stores the agent
writes (ledger, insights) and acts through the same guard, so the dashboard shows the real
system and a human desk action is as audited as an agent action.

    GET  /api/compliance          each recovery-conduct rule, where it is enforced, blocks so far
    GET  /api/overview            KPIs, outcomes, reasons, mood, QA, compliance, speed
    GET  /api/plan                today's planner queue and what happened to each account
    GET  /api/calls               call log (filters: status, outcome, language, flagged, q)
    GET  /api/calls/{id}          transcript, trace spans, review, ledger actions
    GET  /api/live                live calls and alerts (supervisor view)
    GET  /api/desk                escalations for the human desk, routed to teams
    POST /api/desk/{id}           assign / resolve
    POST /api/desk/{id}/assist    agent assist: brief, next best action, suggested replies
    POST /api/assist/ask          answer a question from the loan agreement, with sections
    GET  /api/borrowers           synthetic borrowers, to start a chat
    POST /api/chat/start | /api/chat/{id}/say | /api/chat/{id}/end   test chat as a borrower
    GET  /api/quality             eval results, per-item QA pass rates, AI-vs-human agreement
    POST /api/calls/{id}/coach    supervisor: a private note for the agent's next reply
    POST /api/calls/{id}/takeover supervisor: stop the AI, hand the case to the human desk
    POST /api/calls/{id}/qa       a human's own QA marks for a call (calibrates the AI reviewer)
    GET  /api/export/calls.csv    the call log as a spreadsheet (same filters as /api/calls)
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import statistics
import threading
import time
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from kisht import claims, compliance
from kisht.adapters.call_state import CallNotFound
from kisht.agent import Agent
from kisht.audit import entries_for_call
from kisht.guard import GuardRefused
from kisht.ports import ModelUnavailable
from kisht.review import Reviewer
from kisht.runtime import Runtime
from kisht.wrapup import claim as claim_wrapup

# Run from the repo root (like every kisht command: config.yaml is relative). In Docker the
# package lives in the venv, so paths come from the working directory, not from __file__.
ROOT = Path(os.environ.get("KISHT_ROOT", "."))
DIST = ROOT / "dashboard" / "dist"


class DeskUpdate(BaseModel):
    status: str | None = None          # open | in_progress | resolved
    assignee: str | None = None
    resolution: str | None = None


class Coach(BaseModel):
    note: str = ""
    by: str = "supervisor"


class HumanQA(BaseModel):
    labels: dict[str, str]             # scorecard item id -> pass | fail | na
    by: str = "reviewer"


class Ask(BaseModel):
    question: str
    lender_id: str = "demo-nbfc"


class ChatStart(BaseModel):
    borrower_id: str
    channel: str = "chat"


class ChatSay(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def _pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


def _json_from(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    try:
        return json.loads(m.group()) if m else None
    except json.JSONDecodeError:
        return None


def create_api(rt: Runtime) -> FastAPI:
    app = FastAPI(title="Kisht contact centre")
    turn_locks: dict[str, threading.Lock] = {}
    lock = threading.Lock()

    @app.exception_handler(ModelUnavailable)
    async def model_down(_request: Any, exc: ModelUnavailable) -> JSONResponse:
        """A busy or stopped model server is not a server error of ours: say so plainly."""
        return JSONResponse({"detail": f"The model server is not answering: {exc}"}, 503)

    def lender_of(call: dict):
        return rt.lenders.get(call["lender_id"])

    def review_later(call_id: str, lender) -> None:
        def run():
            Reviewer(rt.models.for_role("reviewer"), rt.insights).review(call_id, lender)
        threading.Thread(target=run, daemon=True).start()

    # ---------- overview ----------

    @app.get("/api/overview")
    def overview() -> dict[str, Any]:
        calls = rt.insights.calls(limit=10_000)
        ended = [c for c in calls if c["status"] == "ended"]
        outcomes = Counter((c["outcome"] or "").split(":")[0] for c in ended)
        escalated = Counter(c["outcome"].split(":")[1] for c in ended
                            if (c["outcome"] or "").startswith("escalated:"))
        wrong = escalated.get("wrong_person", 0)
        # Abandoned or interrupted conversations reached nobody we can vouch for.
        reached = sum(1 for c in ended if c["outcome"] not in (
            "not_verified", "abandoned", "interrupted")) - wrong
        reviews = rt.insights.reviews()
        turns = rt.insights.turn_stats()
        prompt = sum(t["prompt_tokens"] or 0 for t in turns)
        cached = sum(t["cached_tokens"] or 0 for t in turns)
        blocked: Counter = Counter()
        for r in reviews:
            for c in r["compliance"]:
                blocked[c["label"]] += c["blocked"]
        qa_scores = [r["qa_score"] for r in reviews if r["qa_score"] is not None]
        handle = rt.insights.handle_seconds()
        qa_by_call = {r["call_id"]: r["qa_score"] for r in reviews}
        by_language = []
        for lang in sorted({c["language"] for c in ended if c["language"]}):
            mine = [c for c in ended if c["language"] == lang]
            kinds = Counter((c["outcome"] or "").split(":")[0] for c in mine)
            scores = [s for c in mine if (s := qa_by_call.get(c["call_id"])) is not None]
            by_language.append({
                "language": lang, "calls": len(mine),
                "resolved_pct": _pct(kinds["promise"] + kinds["link_sent"], len(mine)),
                "escalated_pct": _pct(kinds["escalated"], len(mine)),
                "qa": round(statistics.mean(scores), 1) if scores else None,
                "blocked": sum(c["blocks"] for c in mine)})
        promises = rt.ledger.db.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM promises").fetchone()
        links = rt.ledger.db.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM payment_links").fetchone()
        return {
            "calls": len(calls), "live": len(calls) - len(ended), "ended": len(ended),
            "rates": {
                "right_party_contact": _pct(reached, len(ended)),
                "promise": _pct(outcomes["promise"], len(ended)),
                "link_sent": _pct(outcomes["link_sent"], len(ended)),
                "escalated": _pct(outcomes["escalated"], len(ended)),
                "opted_out": _pct(outcomes["opted_out"], len(ended)),
                # Containment: of the borrowers we really reached, how many the AI handled
                # to the end without a human.
                "containment": _pct(reached - (outcomes["escalated"] - wrong), reached),
            },
            "handle_time_s": round(statistics.median(handle)) if handle else None,
            "by_language": by_language,
            "money": {"promises": promises[0], "promised_amount": promises[1],
                      "links": links[0], "link_amount": links[1]},
            "outcomes": dict(outcomes), "escalations": dict(escalated),
            "reasons": dict(Counter(r["reason"] for r in reviews)),
            "sentiment": dict(Counter(r["sentiment"] for r in reviews)),
            "languages": dict(Counter(c["language"] for c in calls)),
            "qa": {"average": round(statistics.mean(qa_scores), 1) if qa_scores else None,
                   "reviewed": len(reviews)},
            "blocked": dict(blocked),
            "speed": {
                "median_turn_s": round(statistics.median(secs), 1) if (secs := [
                    t["seconds"] for t in turns if t["seconds"]]) else None,
                "model_calls_per_turn": round(statistics.mean(
                    [t["model_calls"] or 0 for t in turns]), 2) if turns else None,
                "cache_hit_pct": _pct(cached, prompt),
                # Voice only: how long the borrower waits before hearing anything.
                "median_first_words_s": round(statistics.median(firsts), 1) if (firsts := [
                    t["first_s"] for t in turns if t.get("first_s")]) else None,
                "voice_turns": len(firsts)},
        }

    # ---------- rules: where each recovery-conduct rule is enforced ----------

    rules_cache: dict[str, Any] = {"at": 0.0, "value": None}

    @app.get("/api/compliance")
    def rules() -> dict[str, Any]:
        """The rules-to-code table plus how often each rule actually stopped something.
        Cached for 30 s: counting reads every audit file."""
        if rules_cache["value"] and time.monotonic() - rules_cache["at"] < 30:
            return rules_cache["value"]
        book = compliance.load(ROOT / "compliance" / "rbi-recovery-2027.yaml")
        counts = compliance.blocked_counts(ROOT / rt.cfg.stores.audit_dir, rt.insights)
        value = compliance.as_dict(book, counts)
        rules_cache.update(at=time.monotonic(), value=value)
        return value

    # ---------- is everything this page depends on up? ----------

    health_cache: dict[str, Any] = {"at": 0.0, "value": None}

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        """Cheap and cached for 5 s: the dashboard asks every few seconds. The model check
        only says the server answers; `kisht health` runs a real completion."""
        if health_cache["value"] and time.monotonic() - health_cache["at"] < 5:
            return health_cache["value"]
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
        value = {"mode": rt.cfg.mode,
                 "model": {"ok": model_ok, "name": role.model.split("/")[-1], "server": role.server},
                 "call_state": {"ok": redis_ok},
                 "clock": {"now": now.isoformat(timespec="minutes"),
                           "fixed": abs((now - datetime.now(now.tzinfo)).total_seconds()) > 120,
                           "window": f"{window.start:%H:%M}-{window.end:%H:%M}",
                           "open": window.start <= now.time() < window.end}}
        health_cache.update(at=time.monotonic(), value=value)
        return value

    # ---------- today's plan ----------

    @app.get("/api/plan")
    def plan(day: str | None = None) -> dict[str, Any]:
        day = day or (rt.ledger.db.execute("SELECT MAX(plan_date) FROM plans").fetchone()[0])
        if not day:
            return {"date": None, "items": []}
        rows = rt.ledger.db.execute(
            "SELECT p.*, l.borrower_id, l.emi, b.name, b.language, b.city FROM plans p "
            "JOIN loans l ON l.id = p.loan_id JOIN borrowers b ON b.id = l.borrower_id "
            "WHERE p.plan_date=?", (day,)).fetchall()
        contacted = {c["loan_id"]: c for c in reversed(rt.insights.calls(limit=10_000))}
        order = {"high": 0, "medium": 1, "low": 2}
        items = []
        for r in rows:
            d = rt.ledger.dues(r["loan_id"], date.fromisoformat(day))
            c = contacted.get(r["loan_id"])
            items.append({**dict(r), "days_past_due": d.days_past_due,
                          "overdue_amount": d.overdue_amount,
                          "call_id": c["call_id"] if c else None,
                          "outcome": c["outcome"] if c else None})
        items.sort(key=lambda x: (order.get(x["priority"], 3), -x["days_past_due"]))
        return {"date": day, "items": items,
                "counts": dict(Counter(i["priority"] for i in items))}

    # ---------- call log + trace ----------

    @app.get("/api/calls")
    def calls(status: str | None = None, outcome: str | None = None,
              language: str | None = None, flagged: bool = False, q: str | None = None
              ) -> list[dict[str, Any]]:
        return rt.insights.calls(status=status, outcome=outcome, language=language,
                                 flagged=flagged, q=q)

    @app.get("/api/export/calls.csv")
    def calls_csv(status: str | None = None, outcome: str | None = None,
                  language: str | None = None, flagged: bool = False, q: str | None = None
                  ) -> Response:
        cols = ["call_id", "started_utc", "ended_utc", "borrower_name", "loan_id", "channel",
                "language", "status", "outcome", "turns", "blocks", "reason", "sentiment",
                "qa_score", "source", "note"]
        buf = io.StringIO()
        out = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        out.writeheader()
        out.writerows(rt.insights.calls(status=status, outcome=outcome, language=language,
                                        flagged=flagged, q=q, limit=10_000))
        return Response(buf.getvalue(), media_type="text/csv", headers={
            "Content-Disposition": 'attachment; filename="kisht-calls.csv"'})

    def _review_with_humans(call_id: str) -> dict[str, Any] | None:
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

    def _live_guard(call_id: str):
        c = rt.insights.call(call_id)
        if not c:
            raise HTTPException(404, "no such call")
        if c["status"] != "live" or not rt.calls.exists(call_id):
            raise HTTPException(409, "this conversation is no longer live")
        return rt.guards[c["lender_id"]]

    @app.post("/api/calls/{call_id}/coach")
    def coach(call_id: str, body: Coach) -> dict[str, Any]:
        try:
            return _live_guard(call_id).coach(call_id, by=body.by, note=body.note)
        except GuardRefused as e:
            raise HTTPException(409, f"{e.code}: {e.message}") from e

    @app.post("/api/calls/{call_id}/takeover")
    def takeover(call_id: str, body: Coach) -> dict[str, Any]:
        try:
            return _live_guard(call_id).take_over(call_id, by=body.by, note=body.note)
        except GuardRefused as e:
            raise HTTPException(409, f"{e.code}: {e.message}") from e

    @app.post("/api/calls/{call_id}/qa")
    def human_qa(call_id: str, body: HumanQA) -> dict[str, Any]:
        review = rt.insights.review(call_id)
        if not review:
            raise HTTPException(409, "this call has no review yet")
        known = {q["id"] for q in review["qa"]}
        bad = [k for k, v in body.labels.items() if k not in known or v not in
               ("pass", "fail", "na")]
        if bad or not body.labels:
            raise HTTPException(400, f"unknown item or result: {', '.join(bad) or 'none given'}")
        rt.insights.set_qa_labels(call_id, body.labels, body.by[:60] or "reviewer")
        rt.audit.record(call_id=call_id, tenant_id="qa", action="human_qa_review",
                        args={"by": body.by, "items": len(body.labels)}, outcome="ok")
        return _review_with_humans(call_id)

    @app.get("/api/calls/{call_id}")
    def call(call_id: str) -> dict[str, Any]:
        c = rt.insights.call(call_id)
        if not c:
            raise HTTPException(404, "no such call")
        led = rt.ledger.db

        def rows(table: str) -> list[dict]:
            return [dict(r) for r in led.execute(f"SELECT * FROM {table} WHERE call_id=?",
                                                 (call_id,))]
        return {"call": c, "turns": rt.insights.turns(call_id),
                "spans": rt.insights.spans(call_id), "review": _review_with_humans(call_id),
                "actions": {"promises": rows("promises"), "links": rows("payment_links"),
                            "escalations": rows("escalations"), "followups": rows("followups")},
                "audit": entries_for_call(rt.cfg.stores.audit_dir, call_id)
                or [e for e in rt.audit.entries if e["call_id"] == call_id]}

    # ---------- supervisor: live calls + alerts ----------

    @app.get("/api/live")
    def live() -> dict[str, Any]:
        # Safety net only, and late: the sweeper wraps a quiet call up properly after 30
        # minutes (case note, ledger contact, review). At 30 here, this poll won that race
        # and the call got none of those.
        rt.insights.close_stale(max_idle_minutes=120)
        live_calls = []
        for c in rt.insights.calls(status="live", limit=50):
            t = rt.insights.turns(c["call_id"])
            live_calls.append({**c, "last_turns": t[-4:]})
        alerts = []
        for c in rt.insights.calls(limit=40):
            for t in rt.insights.turns(c["call_id"]):
                for kind in (t["replaced"] or []) + (t["refused"] or []):
                    alerts.append({"call_id": c["call_id"], "at": t["at_utc"],
                                   "borrower_name": c["borrower_name"], "kind": kind,
                                   "said": t["agent"][:160]})
            if (c["outcome"] or "").startswith("escalated:"):
                alerts.append({"call_id": c["call_id"], "at": c["ended_utc"],
                               "borrower_name": c["borrower_name"], "kind": c["outcome"],
                               "said": c["note"] or ""})
        alerts.sort(key=lambda a: a["at"] or "", reverse=True)
        return {"live": live_calls, "alerts": alerts[:50]}

    # ---------- human desk + agent assist ----------

    def _desk_item(e: dict) -> dict[str, Any]:
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

    @app.get("/api/desk")
    def desk() -> list[dict[str, Any]]:
        rows = rt.ledger.db.execute(
            "SELECT * FROM escalations ORDER BY created_utc DESC LIMIT 500").fetchall()
        items = [_desk_item(dict(r)) for r in rows]
        # Unresolved first; within those, the case closest to (or furthest past) its deadline.
        items.sort(key=lambda d: (d["status"] == "resolved", d["sla_hours"] - d["age_hours"]))
        return items

    def _escalation(eid: str) -> dict:
        row = rt.ledger.db.execute("SELECT * FROM escalations WHERE id=?", (eid,)).fetchone()
        if not row:
            raise HTTPException(404, "no such escalation")
        return _desk_item(dict(row))

    @app.post("/api/desk/{eid}")
    def desk_update(eid: str, body: DeskUpdate) -> dict[str, Any]:
        item = _escalation(eid)
        status = body.status or item["status"]
        if status not in ("open", "in_progress", "resolved"):
            raise HTTPException(400, "status must be open, in_progress or resolved")
        # The ledger row is what the guard reads for the contact hold (R1): keep it in step,
        # or a resolved case would block agent contact with this borrower for ever.
        if status == "resolved":
            rt.ledger.resolve_escalation(eid)
        else:
            rt.ledger.reopen_escalation(eid)
        rt.insights.set_desk(eid, team=item["team"], status=status,
                             assignee=body.assignee or item["assignee"],
                             resolution=body.resolution or item["resolution"])
        if status == "resolved" and item["status"] != "resolved" and body.resolution:
            # Close the loop: the agent reads this the next time it talks to the borrower.
            loan = rt.ledger.loan(item["loan_id"])
            who = body.assignee or item["assignee"] or item["team"]
            rt.ledger.add_desk_note(
                lender_id=loan["lender_id"], borrower_id=item["borrower_id"],
                loan_id=item["loan_id"],
                note=f"Human desk ({who}) resolved the {item['reason']} case: {body.resolution}")
        rt.audit.record(call_id=item.get("call_id"), tenant_id="desk", action="desk_update",
                        args={"escalation_id": eid, "status": status,
                              "assignee": body.assignee}, outcome="ok")
        return _escalation(eid)

    @app.post("/api/desk/{eid}/assist")
    def assist(eid: str) -> dict[str, Any]:
        item = _escalation(eid)
        loan = rt.ledger.loan(item["loan_id"])
        lender = rt.lenders.get(loan["lender_id"])
        guard = rt.guards[lender.id]
        dues = rt.ledger.dues(item["loan_id"], guard.today()).as_dict()
        turns = rt.insights.turns(item["call_id"]) if item.get("call_id") else []
        convo = "\n".join(f"Borrower: {t['borrower']}\nAgent: {t['agent']}" if t["borrower"]
                          else f"Agent: {t['agent']}" for t in turns)
        notes = rt.ledger.recent_notes(item["borrower_id"])
        prompt = (
            "You assist a human agent at a loan company's " + item["team"] + ". The AI agent "
            "handed this case over. Help the human handle the call back well and within "
            f"policy.\n\nCASE: reason {item['reason']}; AI summary: {item['summary']}\n"
            f"DUES: {json.dumps(dues)}\nPOLICY: promises at most "
            f"{lender.promises.max_days_after_due} days after due; part payment at least "
            f"{lender.promises.min_part_payment_pct}%; waivers, settlements and restructuring "
            "need a manager's approval.\nPAST NOTES: "
            + "; ".join(n["note"] or "" for n in notes) + "\n\nCONVERSATION:\n" + convo +
            "\n\nAnswer with ONLY JSON: {\"brief\": two sentences on the situation, "
            "\"next_best_action\": one sentence, \"suggested_replies\": [three short things the "
            "human could say, in the borrower's language], \"watch_out\": one sentence on "
            "risk or compliance}")
        model = rt.models.for_role("reviewer")
        reply = model.complete([{"role": "user", "content": prompt}])
        data = _json_from(reply.content) or {"brief": reply.content[:400]}
        return {**data, "dues": dues, "notes": notes, "model": model.name}

    @app.post("/api/assist/ask")
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

    # ---------- test chat as a borrower ----------

    @app.get("/api/borrowers")
    def borrowers(q: str | None = None,
                  limit: int = Query(60, ge=1, le=200)) -> list[dict[str, Any]]:
        sql = ("SELECT b.id, b.name, b.language, b.city, l.id AS loan_id, l.emi, l.product "
               "FROM borrowers b JOIN loans l ON l.borrower_id = b.id")
        args: list[Any] = []
        if q:
            sql += " WHERE b.name LIKE ? OR b.id LIKE ? OR b.city LIKE ?"
            args = [f"%{q}%"] * 3
        sql += " ORDER BY b.id LIMIT ?"
        return [dict(r) for r in rt.ledger.db.execute(sql, [*args, limit])]

    @app.post("/api/chat/start")
    def chat_start(body: ChatStart) -> dict[str, Any]:
        b = rt.ledger.borrower(body.borrower_id)
        if not b:
            raise HTTPException(404, "no such borrower")
        loans = rt.ledger.loans_for(body.borrower_id)
        if not loans:
            raise HTTPException(404, "this borrower has no loan")
        guard = rt.guards[b["lender_id"]]
        try:
            agent, greeting = Agent.start(
                guard=guard, calls=rt.calls, model=rt.models.for_role("agent"),
                borrower_id=body.borrower_id, loan_id=loans[0]["id"], channel=body.channel,
                agreement=rt.agreements.get(b["lender_id"]), insights=rt.insights,
                source="dashboard")
        except GuardRefused as e:
            raise HTTPException(409, f"{e.code}: {e.message}") from e
        return {"call_id": agent.call_id, "greeting": greeting, "borrower": b["name"],
                "language": b["language"]}

    def _agent(call_id: str) -> Agent:
        """The agent holds nothing: it is rebuilt from the shared call state on every
        request, so a chat survives a restart of this process and nothing piles up here."""
        try:
            state = rt.calls.get_state(call_id)
        except CallNotFound:
            raise HTTPException(404, "no open chat with this id") from None
        if state.get("status") == "ended" or state.get("tenant_id") not in rt.guards:
            raise HTTPException(404, "no open chat with this id")
        lender_id = state["tenant_id"]
        return Agent(call_id, rt.guards[lender_id], rt.calls, rt.models.for_role("agent"),
                     rt.agreements.get(lender_id), rt.insights)

    def _turn_lock(call_id: str) -> threading.Lock:
        with lock:
            return turn_locks.setdefault(call_id, threading.Lock())

    @app.post("/api/chat/{call_id}/say")
    def chat_say(call_id: str, body: ChatSay) -> dict[str, Any]:
        agent = _agent(call_id)
        with _turn_lock(call_id):          # a double send must not run two turns at once
            t = agent.handle(body.text)
        return {"reply": t.reply, "tools": t.tool_calls, "refused": t.refused,
                "replaced": t.replaced, "promise_saved": t.promise_saved, "ended": t.ended,
                "seconds": round(t.model_latency_s, 1)}

    @app.post("/api/chat/{call_id}/end")
    def chat_end(call_id: str) -> dict[str, Any]:
        agent = _agent(call_id)
        if not claim_wrapup(rt.calls, call_id):      # the sweeper is closing it right now
            raise HTTPException(409, "this chat is already being closed")
        with _turn_lock(call_id):
            done = agent.finish()
        with lock:
            turn_locks.pop(call_id, None)
        review_later(call_id, agent.lender)
        return done

    # ---------- quality: evals + QA ----------

    @app.get("/api/quality")
    def quality() -> dict[str, Any]:
        evals = []
        for f in sorted((ROOT / "results" / "evals").glob("*/summary.json")):
            try:
                data = json.loads(f.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            evals.append({"run": f.parent.name, **data})
        reviews = rt.insights.reviews()
        items: dict[str, Counter] = {}
        for r in reviews:
            for q in r["qa"]:
                items.setdefault(q["id"], Counter())[q["result"]] += 1
        failing: dict[str, list[str]] = {}
        ai: dict[tuple[str, str], dict] = {}
        for r in sorted(reviews, key=lambda r: r["started_utc"], reverse=True):
            for q in r["qa"]:
                ai[(r["call_id"], q["id"])] = q
                if q["result"] == "fail":
                    failing.setdefault(q["id"], []).append(r["call_id"])
        qa_items = [{"id": k, "pass": v["pass"], "fail": v["fail"], "na": v["na"],
                     "pass_rate": _pct(v["pass"], v["pass"] + v["fail"]),
                     "failing_calls": failing.get(k, [])[:5]}
                    for k, v in items.items()]
        # Calibration: a human marked the same items. Only items the model judged count
        # (the code-checked item cannot disagree with itself).
        pairs = [(lab, ai[(lab["call_id"], lab["item_id"])]) for lab in rt.insights.qa_labels()
                 if (lab["call_id"], lab["item_id"]) in ai
                 and ai[(lab["call_id"], lab["item_id"])].get("by") == "model"]
        agree = sum(1 for lab, q in pairs if lab["result"] == q["result"])
        calibration = {
            "calls": len({lab["call_id"] for lab, _ in pairs}), "items": len(pairs),
            "agreement_pct": _pct(agree, len(pairs)),
            "disagreements": [{"call_id": lab["call_id"], "item": lab["item_id"],
                               "ai": q["result"], "human": lab["result"], "by": lab["by"]}
                              for lab, q in pairs if lab["result"] != q["result"]][:30]}
        return {"evals": evals, "qa_items": qa_items, "calibration": calibration,
                "claims": claim_numbers()}

    claims_cache: dict[str, Any] = {"at": 0.0, "value": None}

    def claim_numbers() -> dict[str, Any]:
        """Claims with no action behind them (src/kisht/claims.py): in the eval runs, where a
        pass rate can be split by them, and in the call log. Cached for a minute."""
        if claims_cache["value"] and time.monotonic() - claims_cache["at"] < 60:
            return claims_cache["value"]
        runs = [d for d in (ROOT / "results" / "evals" / n for n in claims.PUBLISHED_RUNS)
                if (d / "runs.jsonl").exists()]
        value = {
            "eval_runs": [d.name for d in runs],
            "evals": claims.summarise([c for d in runs for c in claims.from_eval_run(
                d, ROOT / "evals" / "personas.yaml")]) if runs else {},
            "calls": claims.summarise(claims.from_call_log(
                rt.insights, ROOT / rt.cfg.stores.audit_dir)),
            "kinds": claims.KIND_WORDS}
        claims_cache.update(at=time.monotonic(), value=value)
        return value

    # ---------- the dashboard itself ----------

    if DIST.exists():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            # The page shell must never be cached: asset names change on every build.
            return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})

    return app
