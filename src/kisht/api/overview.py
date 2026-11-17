"""The overview page: contact rates, money, language table, QA, compliance and speed."""
from __future__ import annotations

import statistics
from collections import Counter
from typing import Any

from fastapi import APIRouter

from kisht.api.common import ALL_ROWS, Ctx, pct

# Abandoned or interrupted conversations reached nobody we can vouch for.
NOT_REACHED = ("not_verified", "abandoned", "interrupted")


def _kind(outcome: str | None) -> str:
    return (outcome or "").split(":")[0]


def _mean(xs: list[float], places: int = 1) -> float | None:
    return round(statistics.mean(xs), places) if xs else None


def _median(xs: list[float], places: int = 1) -> float | None:
    return round(statistics.median(xs), places) if xs else None


def router(ctx: Ctx) -> APIRouter:
    rt = ctx.rt
    r = APIRouter()

    @r.get("/api/overview")
    def overview() -> dict[str, Any]:
        calls = rt.insights.calls(limit=ALL_ROWS)
        ended = [c for c in calls if c["status"] == "ended"]
        outcomes = Counter(_kind(c["outcome"]) for c in ended)
        escalated = Counter(c["outcome"].split(":")[1] for c in ended
                            if (c["outcome"] or "").startswith("escalated:"))
        wrong = escalated.get("wrong_person", 0)
        reached = sum(1 for c in ended if c["outcome"] not in NOT_REACHED) - wrong
        reviews = rt.insights.reviews()
        turns = rt.insights.turn_stats()
        blocked: Counter = Counter()
        for rev in reviews:
            for c in rev["compliance"]:
                blocked[c["label"]] += c["blocked"]
        handle = rt.insights.handle_seconds()
        promises = rt.ledger.db.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM promises").fetchone()
        links = rt.ledger.db.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM payment_links").fetchone()
        n = len(ended)
        return {
            "calls": len(calls), "live": len(calls) - n, "ended": n,
            "rates": {
                "right_party_contact": pct(reached, n),
                "promise": pct(outcomes["promise"], n),
                "link_sent": pct(outcomes["link_sent"], n),
                "escalated": pct(outcomes["escalated"], n),
                "opted_out": pct(outcomes["opted_out"], n),
                # Containment: of the borrowers we really reached, how many the AI handled
                # to the end without a human.
                "containment": pct(reached - (outcomes["escalated"] - wrong), reached),
            },
            "handle_time_s": round(statistics.median(handle)) if handle else None,
            "by_language": _by_language(ended, reviews),
            "money": {"promises": promises[0], "promised_amount": promises[1],
                      "links": links[0], "link_amount": links[1]},
            "outcomes": dict(outcomes), "escalations": dict(escalated),
            "reasons": dict(Counter(rev["reason"] for rev in reviews)),
            "sentiment": dict(Counter(rev["sentiment"] for rev in reviews)),
            "languages": dict(Counter(c["language"] for c in calls)),
            "qa": {"average": _mean([rev["qa_score"] for rev in reviews
                                     if rev["qa_score"] is not None]),
                   "reviewed": len(reviews)},
            "blocked": dict(blocked),
            "speed": _speed(turns),
        }

    return r


def _by_language(ended: list[dict], reviews: list[dict]) -> list[dict[str, Any]]:
    qa_by_call = {rev["call_id"]: rev["qa_score"] for rev in reviews}
    groups: dict[str, list[dict]] = {}
    for c in ended:
        if c["language"]:
            groups.setdefault(c["language"], []).append(c)
    out = []
    for lang in sorted(groups):
        mine = groups[lang]
        kinds = Counter(_kind(c["outcome"]) for c in mine)
        scores = [s for c in mine if (s := qa_by_call.get(c["call_id"])) is not None]
        out.append({"language": lang, "calls": len(mine),
                    "resolved_pct": pct(kinds["promise"] + kinds["link_sent"], len(mine)),
                    "escalated_pct": pct(kinds["escalated"], len(mine)),
                    "qa": _mean(scores),
                    "blocked": sum(c["blocks"] for c in mine)})
    return out


def _speed(turns: list[dict]) -> dict[str, Any]:
    prompt = sum(t["prompt_tokens"] or 0 for t in turns)
    cached = sum(t["cached_tokens"] or 0 for t in turns)
    firsts = [t["first_s"] for t in turns if t.get("first_s")]
    return {
        "median_turn_s": _median([t["seconds"] for t in turns if t["seconds"]]),
        "model_calls_per_turn": _mean([t["model_calls"] or 0 for t in turns], 2),
        "cache_hit_pct": pct(cached, prompt),
        # Voice only: how long the borrower waits before hearing anything.
        "median_first_words_s": _median(firsts),
        "voice_turns": len(firsts)}
