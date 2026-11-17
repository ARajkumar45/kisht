"""Quality: eval results, per-item QA pass rates, how often the AI reviewer agrees with a
human, and claims with no action behind them."""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from fastapi import APIRouter

from kisht import claims
from kisht.api.common import ROOT, Ctx, TTLCache, pct

EVALS_DIR = ROOT / "results" / "evals"


def router(ctx: Ctx) -> APIRouter:
    rt = ctx.rt
    r = APIRouter()
    claims_cache, evals_cache = TTLCache(60), TTLCache(60)

    def claim_numbers() -> dict[str, Any]:
        """Claims with no action behind them (src/kisht/claims.py): in the eval runs, where a
        pass rate can be split by them, and in the call log."""
        runs = [d for d in (EVALS_DIR / n for n in claims.PUBLISHED_RUNS)
                if (d / "runs.jsonl").exists()]
        return {
            "eval_runs": [d.name for d in runs],
            "evals": claims.summarise([c for d in runs for c in claims.from_eval_run(
                d, ROOT / "evals" / "personas.yaml")]) if runs else {},
            "calls": claims.summarise(claims.from_call_log(
                rt.insights, ROOT / rt.cfg.stores.audit_dir)),
            "kinds": claims.KIND_WORDS}

    @r.get("/api/quality")
    def quality() -> dict[str, Any]:
        reviews = rt.insights.reviews()
        return {"evals": evals_cache.get(eval_summaries), "qa_items": qa_items(reviews),
                "calibration": calibration(reviews, rt.insights.qa_labels()),
                "claims": claims_cache.get(claim_numbers)}

    return r


def eval_summaries() -> list[dict[str, Any]]:
    out = []
    for f in sorted(EVALS_DIR.glob("*/summary.json")):
        try:
            out.append({"run": f.parent.name, **json.loads(f.read_text())})
        except (OSError, json.JSONDecodeError):
            continue
    return out


def qa_items(reviews: list[dict]) -> list[dict[str, Any]]:
    counts: dict[str, Counter] = {}
    failing: dict[str, list[str]] = {}
    for rev in sorted(reviews, key=lambda x: x["started_utc"], reverse=True):
        for q in rev["qa"]:
            counts.setdefault(q["id"], Counter())[q["result"]] += 1
            if q["result"] == "fail":
                failing.setdefault(q["id"], []).append(rev["call_id"])
    return [{"id": k, "pass": v["pass"], "fail": v["fail"], "na": v["na"],
             "pass_rate": pct(v["pass"], v["pass"] + v["fail"]),
             "failing_calls": failing.get(k, [])[:5]}
            for k, v in counts.items()]


def calibration(reviews: list[dict], labels: list[dict]) -> dict[str, Any]:
    """A human marked the same items as the AI. Only items the model judged count (the
    code-checked item cannot disagree with itself)."""
    ai = {(rev["call_id"], q["id"]): q for rev in reviews for q in rev["qa"]}
    pairs = [(lab, q) for lab in labels
             if (q := ai.get((lab["call_id"], lab["item_id"]))) and q.get("by") == "model"]
    agree = sum(1 for lab, q in pairs if lab["result"] == q["result"])
    return {"calls": len({lab["call_id"] for lab, _ in pairs}), "items": len(pairs),
            "agreement_pct": pct(agree, len(pairs)),
            "disagreements": [{"call_id": lab["call_id"], "item": lab["item_id"],
                               "ai": q["result"], "human": lab["result"], "by": lab["by"]}
                              for lab, q in pairs if lab["result"] != q["result"]][:30]}
