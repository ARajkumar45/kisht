"""Kisht command line.

    uv run kisht health                      # each model role: run a tiny real completion
    uv run kisht due [--today YYYY-MM-DD]    # accounts due for a reminder today
    uv run kisht plan                        # the planner agent decides today's outreach queue
    uv run kisht chat --borrower br_0003     # be the borrower; the agent contacts you by chat
    uv run kisht bridge                      # voice: the endpoint Bolna uses as its LLM (:5050)
    uv run kisht simulate --n 16             # plan today + 16 simulated calls, reviewed
    uv run kisht serve                       # contact-centre dashboard + API (:8000)

While chatting: /state  /audit  /telemetry  /quit
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime

from kisht.adapters.call_state import RedisCallState
from kisht.adapters.llm import health_check
from kisht.agent import Agent
from kisht.audit import AuditLog
from kisht.config import LLMFactory, load_config
from kisht.guard import GuardRefused, PolicyGuard
from kisht.ledger import SqliteLedger
from kisht.lender import LenderRegistry
from kisht.planner import Planner
from kisht.runtime import build

DIM, BOLD, END = "\033[2m", "\033[1m", "\033[0m"


def _setup(args):
    cfg = load_config(args.config)
    lender = LenderRegistry.from_dir(cfg.lenders_dir).get(args.lender)
    ledger = SqliteLedger(cfg.stores.ledger_db)
    return cfg, lender, ledger


def cmd_health(args) -> int:
    cfg = load_config(args.config)
    factory = LLMFactory(cfg)
    ok = True
    for role in cfg.llm_roles:
        r = health_check(factory.for_role(role))
        ok &= r["ok"]
        print(f"{role:10} {'OK ' if r['ok'] else 'BAD'} {r}")
    return 0 if ok else 1


def cmd_due(args) -> int:
    _, lender, ledger = _setup(args)
    today = args.today or date.today()
    rows = ledger.due_accounts(lender.id, today)
    for r in rows:
        flags = " ".join(f for f in ("dnd" if r["dnd"] else "",
                                     "opted-out" if r["opted_out"] else "",
                                     "promise" if r["open_promise"] else "") if f)
        print(f"{r['borrower_id']}  {r['loan_id']}  {r['name']:18} {r['language']}  "
              f"dpd={r['days_past_due']:>2}  overdue=Rs {r['overdue_amount']:>6}  "
              f"next={r['next_due_date']}  {flags}")
    print(f"{DIM}{len(rows)} account(s) due as of {today}{END}")
    return 0


def cmd_chat(args) -> int:
    now = None
    if args.at:
        fixed = datetime.fromisoformat(args.at)
        now = lambda: fixed
    rt = build(args.config, now=now)
    try:
        rt.calls.r.ping()
    except Exception as e:  # noqa: BLE001 - show any connection problem plainly
        print(f"Cannot reach Redis at {rt.cfg.stores.redis_url}: {e}", file=sys.stderr)
        return 2
    cfg, lender, ledger, calls = rt.cfg, rt.lenders.get(args.lender), rt.ledger, rt.calls
    guard = rt.guards[lender.id]
    loans = ledger.loans_for(args.borrower)
    if not loans:
        print(f"No loans for {args.borrower}. Try: uv run kisht due", file=sys.stderr)
        return 2
    model = LLMFactory(cfg).for_role("agent")
    try:
        agent, greeting = Agent.start(guard=guard, calls=calls, model=model,
                                      borrower_id=args.borrower, loan_id=loans[0]["id"],
                                      channel="chat", agreement=rt.agreements.get(lender.id),
                                      insights=rt.insights)
    except GuardRefused as e:
        print(f"Not allowed to contact now: {e.code}: {e.message}", file=sys.stderr)
        return 1
    print(f"{DIM}conversation {agent.call_id} · {lender.name} · {model.name}{END}")
    print(f"{BOLD}agent>{END} {greeting}")
    while True:
        try:
            line = input(f"{BOLD}you>{END} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line == "/quit":
            break
        if line == "/state":
            print(json.dumps(calls.get_state(agent.call_id), indent=2, ensure_ascii=False))
            continue
        if line == "/audit":
            for e in rt.audit.for_call(agent.call_id):
                print(f"{DIM}{e['outcome']:6} {e['action']:20} {e['detail']}{END}")
            continue
        if line == "/telemetry":
            print(json.dumps(rt.audit.telemetry(rt.audit.for_call(agent.call_id)), indent=2))
            continue
        t = agent.handle(line)
        print(f"{BOLD}agent>{END} {t.reply}")
        notes = [f"{t.model_latency_s:.1f}s", f"{t.model_calls} model call(s)"]
        if t.tool_calls:
            notes.append("tools: " + ", ".join(t.tool_calls))
        if t.refused:
            notes.append("guard said no: " + ", ".join(t.refused))
        if t.replaced:
            notes.append("reply replaced: " + ", ".join(t.replaced))
        if t.promise_saved:
            notes.append("PROMISE SAVED")
        print(f"{DIM}  [{' · '.join(notes)}]{END}")
        if t.ended:
            print(f"{DIM}  conversation ended by {t.ended}{END}")
            break
    end = agent.finish()
    print(f"{DIM}outcome: {end['outcome']} · case note: {end['note']}{END}")
    return 0


def cmd_plan(args) -> int:
    cfg, lender, ledger = _setup(args)
    calls = RedisCallState.from_url(cfg.stores.redis_url)
    audit = AuditLog(f"{cfg.stores.audit_dir}/kisht_{datetime.now():%Y%m%d}.jsonl")
    now = None
    if args.at:
        fixed = datetime.fromisoformat(args.at)
        now = lambda: fixed
    guard = PolicyGuard(lender, ledger, calls, audit, now=now)
    result = Planner(guard, LLMFactory(cfg).for_role("planner")).plan()
    for p in result.queue[: args.show]:
        print(f"{p.priority:6} {p.channel:5} {p.loan_id}  dpd={p.days_past_due:>2}  "
              f"{p.reason}  ->  {p.approach}")
    print(f"{DIM}queued {len(result.queue)} · blocked by guard {len(result.blocked)} "
          f"{dict(_count(r for _, r in result.blocked))} · left out by the model "
          f"{len(result.unplanned)} · {result.model_calls} model calls in "
          f"{result.seconds:.0f}s{END}")
    return 0


def _count(items):
    out: dict[str, int] = {}
    for x in items:
        out[x] = out.get(x, 0) + 1
    return out


def cmd_bridge(args) -> int:
    import uvicorn

    from kisht.voice_bridge import VoiceBridge, create_app

    rt = build(args.config, audit_name="voice")
    bridge = VoiceBridge(lenders=rt.lenders, guards=rt.guards, calls=rt.calls,
                         model=rt.models.for_role("agent"), agreements=rt.agreements,
                         insights=rt.insights, reviewer_model=_reviewer(rt))
    _sweeper(rt)                 # a call that just goes quiet still gets its note and review
    uvicorn.run(create_app(bridge), host=args.host, port=args.port, log_level="warning")
    return 0


def _reviewer(rt):
    return rt.models.for_role("reviewer") if "reviewer" in rt.cfg.llm_roles else None


def _sweeper(rt):
    from kisht.wrapup import start_sweeper

    return start_sweeper(insights=rt.insights, calls=rt.calls, guards=rt.guards,
                         agent_model=rt.models.for_role("agent"), reviewer_model=_reviewer(rt),
                         agreements=rt.agreements)


def cmd_simulate(args) -> int:
    from kisht.simulate_day import simulate_day

    now = datetime.fromisoformat(args.at) if args.at else datetime.now().astimezone()
    rt = build(args.config, audit_name="simday", now=lambda: now)
    simulate_day(rt, lender_id=args.lender, now=now, n=args.n, workers=args.workers,
                 replan=args.replan)
    return 0


def cmd_review(args) -> int:
    from kisht.review import Reviewer

    rt = build(args.config, audit_name="review")
    ids = ([c["call_id"] for c in rt.insights.calls(status="ended", limit=100_000)]
           if args.all else rt.insights.unreviewed())
    reviewer = Reviewer(rt.models.for_role("reviewer"), rt.insights)
    for i, call_id in enumerate(ids, 1):
        r = reviewer.review(call_id, rt.lenders.get(rt.insights.call(call_id)["lender_id"]))
        print(f"{i}/{len(ids)} {call_id[:8]} {r['reason']:16} QA {r['qa_score']}")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from kisht.api import create_api

    now = None
    if args.at:                       # demo clock: test chat works outside the calling window
        fixed = datetime.fromisoformat(args.at)
        now = lambda: fixed
    rt = build(args.config, audit_name="dashboard", now=now)
    _sweeper(rt)
    print(f"Kisht dashboard: http://{args.host}:{args.port}"
          + (f"  (clock fixed at {args.at})" if args.at else ""))
    uvicorn.run(create_api(rt), host=args.host, port=args.port, log_level="warning")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="kisht")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--lender", default="demo-nbfc")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health")
    d = sub.add_parser("due")
    d.add_argument("--today", type=date.fromisoformat)
    c = sub.add_parser("chat")
    c.add_argument("--borrower", required=True)
    c.add_argument("--at", help="fixed clock for demos, e.g. 2026-11-10T10:00:00+05:30")
    pl = sub.add_parser("plan")
    pl.add_argument("--at", help="fixed clock, e.g. 2026-11-10T09:00:00+05:30")
    pl.add_argument("--show", type=int, default=15)
    br = sub.add_parser("bridge")
    br.add_argument("--host", default="127.0.0.1")
    br.add_argument("--port", type=int, default=5050)
    sm = sub.add_parser("simulate", help="plan the day and run N simulated conversations")
    sm.add_argument("--n", type=int, default=16)
    sm.add_argument("--workers", type=int, default=2)
    sm.add_argument("--replan", action="store_true", help="plan again even if today has a plan")
    sm.add_argument("--at", help="fixed clock, e.g. 2026-11-11T10:00:00+05:30")
    rv = sub.add_parser("review", help="post-call QA review for calls not yet reviewed")
    rv.add_argument("--all", action="store_true", help="review every ended call again")
    sv = sub.add_parser("serve", help="dashboard + API")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--at", help="fixed clock for demos, e.g. 2026-11-12T11:00:00+05:30")
    args = p.parse_args(argv)
    return {"health": cmd_health, "due": cmd_due, "chat": cmd_chat, "plan": cmd_plan,
            "bridge": cmd_bridge, "simulate": cmd_simulate, "review": cmd_review,
            "serve": cmd_serve}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
