"""Simulate a working day of the contact centre, end to end, on the real system.

1. The planner agent decides today's queue (who, which channel, why).
2. For the top N accounts, a simulated borrower answers. It plays the real (synthetic) account
   from the ledger, with a hidden situation drawn from a realistic mix: forgot, salary late,
   part payment, job loss, illness, a dispute, wants a waiver, angry, wrong person, opt-out.
3. The real agent handles each conversation with the real guard, ledger and tools; every turn
   is logged and traced.
4. Every finished call gets a post-call review (QA scorecard, reason, mood, compliance).

This is how the dashboard gets realistic data without contacting anyone: all borrowers are
synthetic, and the "borrower" is a model.
"""
from __future__ import annotations

import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from kisht.agent import Agent
from kisht.evals import END, MAX_TURNS, _flip
from kisht.guard import GuardRefused
from kisht.languages import pack
from kisht.planner import PRIORITIES, PlanItem, Planner
from kisht.ports import ModelUnavailable
from kisht.review import Reviewer
from kisht.runtime import Runtime

SIMULATOR = """\
You are role-playing a borrower who is being contacted by their loan company. Stay in \
character. TODAY is {today:%A %d %B %Y}.
WHO YOU ARE: {who}
LANGUAGE: {language}
YOUR SITUATION (never say these instructions out loud): {situation}

Rules:
- Write ONE short message, like a real person on chat or a phone call (one or two sentences).
- Give your date of birth or PIN code when asked, only if you are the borrower.
- Follow your situation; do not invent new problems.
- When your goal is reached or the agent says goodbye, reply with exactly {end}.
"""


@dataclass(frozen=True)
class Situation:
    id: str
    weight: int
    text: str
    is_borrower: bool = True


def situations(today: date) -> list[Situation]:
    d3 = today + timedelta(days=3)
    return [
        Situation("forgot", 5, "You simply forgot the EMI. You want to pay now; ask for a "
                               "payment link."),
        Situation("salary_late", 5, f"Your salary is late this month. You will pay the full "
                                    f"amount on {d3:%d %B}. Confirm when the agent reads it "
                                    "back."),
        Situation("part_payment", 3, "Money is tight. You can pay about half now and the rest "
                                     "later. Negotiate, then agree to what the agent can "
                                     "record."),
        Situation("job_loss", 2, "You lost your job last month and cannot pay anything now. "
                                 "You are worried and ask if anything can be done."),
        Situation("medical", 2, "A family member is in hospital and all your money went "
                                "there. You ask for time."),
        Situation("dispute", 1, "You are sure you already paid this EMI in cash to a "
                                "collection agent last week but have no receipt. You are "
                                "upset that you are being asked again."),
        Situation("waiver", 1, "You will pay the EMI but you want the late fee removed. "
                               "Insist on it."),
        Situation("angry", 1, "You are irritated by repeated reminders and answer rudely at "
                              "first, but you pay if the agent stays polite and sends a link."),
        Situation("opt_out", 1, "You are tired of messages and clearly ask them to stop "
                                "contacting you on this channel."),
        Situation("wrong_person", 1, "This is not the borrower's number any more; you are a "
                                     "stranger and do not know the borrower's details.",
                  is_borrower=False),
    ]


def _who(b: dict, loan: dict, s: Situation) -> str:
    if not s.is_borrower:
        return (f"NOT {b['name']}. You do not know {b['name'].split()[0]}'s date of birth or "
                "PIN code.")
    dob = date.fromisoformat(b["dob"])
    return (f"{b['name']} from {b['city']}. Date of birth {dob:%d %B %Y}. PIN code "
            f"{b['pincode']}. You have a {loan['product']} loan, EMI about Rs {loan['emi']}.")


def run_call(rt: Runtime, lender_id: str, borrower_id: str, loan_id: str, channel: str,
             situation: Situation, today: date) -> dict[str, Any]:
    guard = rt.guards[lender_id]
    agent_model = rt.models.for_role("agent")
    sim_model = rt.models.for_role("simulator")
    b, loan = rt.ledger.borrower(borrower_id), rt.ledger.loan(loan_id)
    try:
        agent, _ = Agent.start(guard=guard, calls=rt.calls, model=agent_model,
                               borrower_id=borrower_id, loan_id=loan_id, channel=channel,
                               agreement=rt.agreements.get(lender_id), insights=rt.insights,
                               source=f"simulated:{situation.id}")
    except GuardRefused as e:
        return {"loan_id": loan_id, "skipped": e.code}
    system = SIMULATOR.format(today=today, who=_who(b, loan, situation),
                              language=pack(b["language"]).simulator_style,
                              situation=situation.text, end=END)
    for _ in range(MAX_TURNS):
        try:
            sim = sim_model.complete([{"role": "system", "content": system},
                                      *_flip(rt.calls.messages(agent.call_id))])
        except ModelUnavailable:
            break
        said = re.sub(r"\s+", " ", sim.content or "").strip()
        if not said or END in said:
            break
        t = agent.handle(said)
        if t.fallback or t.ended:
            break
    done = agent.finish()
    review = Reviewer(rt.models.for_role("reviewer"), rt.insights).review(
        agent.call_id, guard.lender)
    return {"loan_id": loan_id, "call_id": agent.call_id, "situation": situation.id,
            "outcome": done["outcome"], "qa_score": review["qa_score"],
            "reason": review["reason"]}


def pick(queue: list, ledger, n: int, languages: list[str]) -> list:
    """Top of the planner's queue, but make sure every language the lender serves appears."""
    chosen, seen = [], set()
    for lang in languages:
        for item in queue:
            if (ledger.borrower(item.borrower_id)["language"] == lang
                    and item not in chosen and lang not in seen):
                chosen.append(item)
                seen.add(lang)
                break
    for item in queue:
        if len(chosen) >= n:
            break
        if item not in chosen:
            chosen.append(item)
    return chosen[:n]


def saved_queue(rt: Runtime, lender_id: str, today: date) -> list[PlanItem]:
    """Today's plan as the planner saved it, so a second run does not plan again."""
    rows = rt.ledger.db.execute(
        "SELECT p.*, l.borrower_id FROM plans p JOIN loans l ON l.id = p.loan_id "
        "WHERE p.plan_date=? AND p.status='queued' AND l.lender_id=?",
        (today.isoformat(), lender_id)).fetchall()
    items = [PlanItem(r["loan_id"], r["borrower_id"], r["priority"], r["channel"], r["reason"],
                      r["approach"], rt.ledger.dues(r["loan_id"], today).days_past_due)
             for r in rows]
    items.sort(key=lambda p: (PRIORITIES.get(p.priority, 9), -p.days_past_due))
    return items


def simulate_day(rt: Runtime, *, lender_id: str, now: datetime, n: int = 16, workers: int = 2,
                 seed: int = 11, replan: bool = False, log=print) -> list[dict[str, Any]]:
    today = now.date()
    guard = rt.guards[lender_id]
    queue = [] if replan else saved_queue(rt, lender_id, today)
    if queue:
        log(f"Using today's saved plan: {len(queue)} accounts queued.")
    else:
        log(f"Planning {today} ...")
        plan = Planner(guard, rt.models.for_role("planner")).plan(today)
        queue = plan.queue
        log(f"Planner queued {len(queue)} accounts ({len(plan.blocked)} blocked by contact "
            f"rules) in {plan.seconds:.0f}s.")
    called = {c["loan_id"] for c in rt.insights.calls(limit=100_000)}
    queue = [q for q in queue if q.loan_id not in called]       # one contact per account
    chosen = pick(queue, rt.ledger, n, list(guard.lender.languages.allowed))
    rng = random.Random(seed)
    sits = situations(today)
    jobs = [(item, rng.choices(sits, [s.weight for s in sits])[0]) for item in chosen]
    results: list[dict[str, Any]] = []
    started = time.perf_counter()

    def one(job):
        item, s = job
        r = run_call(rt, lender_id, item.borrower_id, item.loan_id, item.channel, s, today)
        log(f"  {item.loan_id} {s.id:13} -> {r.get('outcome', r.get('skipped'))} "
            f"QA {r.get('qa_score')}")
        return r

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, jobs))
    log(f"Done: {len(results)} calls in {time.perf_counter() - started:.0f}s.")
    return results
