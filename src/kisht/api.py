"""The contact-centre API behind the dashboard. Everything here reads the same stores the agent
writes (ledger, insights) and acts through the same guard, so the dashboard shows the real
system and a human desk action is as audited as an agent action.

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
    GET  /api/quality             eval results and per-item QA pass rates
"""
from __future__ import annotations

import json
import re
import statistics
import threading
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from kisht.agent import Agent
from kisht.guard import GuardRefused
from kisht.review import Reviewer
from kisht.runtime import Runtime

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "dashboard" / "dist"


class DeskUpdate(BaseModel):
    status: str | None = None          # open | in_progress | resolved
    assignee: str | None = None
    resolution: str | None = None


class Ask(BaseModel):
    question: str
    lender_id: str = "demo-nbfc"


class ChatStart(BaseModel):
    borrower_id: str
    channel: str = "chat"


class ChatSay(BaseModel):
    text: str


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
    agents: dict[str, Agent] = {}
    lock = threading.Lock()

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
        reached = sum(1 for c in ended if c["outcome"] != "not_verified") - wrong
        reviews = rt.insights.reviews()
        turns = [t for c in ended for t in rt.insights.turns(c["call_id"]) if t["borrower"]]
        prompt = sum(t["prompt_tokens"] or 0 for t in turns)
        cached = sum(t["cached_tokens"] or 0 for t in turns)
        blocked: Counter = Counter()
        for r in reviews:
            for c in r["compliance"]:
                blocked[c["label"]] += c["blocked"]
        qa_scores = [r["qa_score"] for r in reviews if r["qa_score"] is not None]
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
            },
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
                "median_turn_s": round(statistics.median(
                    [t["seconds"] for t in turns if t["seconds"]]), 1) if turns else None,
                "model_calls_per_turn": round(statistics.mean(
                    [t["model_calls"] or 0 for t in turns]), 2) if turns else None,
                "cache_hit_pct": _pct(cached, prompt)},
        }

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
                "spans": rt.insights.spans(call_id), "review": rt.insights.review(call_id),
                "actions": {"promises": rows("promises"), "links": rows("payment_links"),
                            "escalations": rows("escalations"), "followups": rows("followups")},
                "audit": [e for e in rt.audit.entries if e["call_id"] == call_id]}

    # ---------- supervisor: live calls + alerts ----------

    @app.get("/api/live")
    def live() -> dict[str, Any]:
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
        return {**e, "borrower_id": b["id"], "borrower_name": b["name"],
                "language": b["language"], "city": b["city"], "emi": loan["emi"],
                "team": state.get("team") or lender.team_for(e["reason"]),
                "status": state.get("status") or "open", "assignee": state.get("assignee"),
                "resolution": state.get("resolution"),
                "review": {"summary": review["summary"], "sentiment": review["sentiment"]}
                if review else None}

    @app.get("/api/desk")
    def desk() -> list[dict[str, Any]]:
        rows = rt.ledger.db.execute("SELECT * FROM escalations ORDER BY created_utc DESC")
        return [_desk_item(dict(r)) for r in rows]

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
        rt.insights.set_desk(eid, team=item["team"], status=status,
                             assignee=body.assignee or item["assignee"],
                             resolution=body.resolution or item["resolution"])
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
    def borrowers(q: str | None = None, limit: int = 60) -> list[dict[str, Any]]:
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
        guard = rt.guards[b["lender_id"]]
        try:
            agent, greeting = Agent.start(
                guard=guard, calls=rt.calls, model=rt.models.for_role("agent"),
                borrower_id=body.borrower_id, loan_id=loans[0]["id"], channel=body.channel,
                agreement=rt.agreements.get(b["lender_id"]), insights=rt.insights,
                source="dashboard")
        except GuardRefused as e:
            raise HTTPException(409, f"{e.code}: {e.message}") from e
        with lock:
            agents[agent.call_id] = agent
        return {"call_id": agent.call_id, "greeting": greeting, "borrower": b["name"],
                "language": b["language"]}

    def _agent(call_id: str) -> Agent:
        with lock:
            agent = agents.get(call_id)
        if not agent:
            raise HTTPException(404, "no open chat with this id")
        return agent

    @app.post("/api/chat/{call_id}/say")
    def chat_say(call_id: str, body: ChatSay) -> dict[str, Any]:
        agent = _agent(call_id)
        t = agent.handle(body.text)
        return {"reply": t.reply, "tools": t.tool_calls, "refused": t.refused,
                "replaced": t.replaced, "promise_saved": t.promise_saved, "ended": t.ended,
                "seconds": round(t.model_latency_s, 1)}

    @app.post("/api/chat/{call_id}/end")
    def chat_end(call_id: str) -> dict[str, Any]:
        agent = _agent(call_id)
        done = agent.finish()
        with lock:
            agents.pop(call_id, None)
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
        items: dict[str, Counter] = {}
        for r in rt.insights.reviews():
            for q in r["qa"]:
                items.setdefault(q["id"], Counter())[q["result"]] += 1
        qa_items = [{"id": k, "pass": v["pass"], "fail": v["fail"], "na": v["na"],
                     "pass_rate": _pct(v["pass"], v["pass"] + v["fail"])}
                    for k, v in items.items()]
        return {"evals": evals, "qa_items": qa_items}

    # ---------- the dashboard itself ----------

    if DIST.exists():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            return FileResponse(DIST / "index.html")

    return app
