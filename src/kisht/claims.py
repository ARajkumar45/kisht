"""Claim versus action: how often the model says it did something it did not do.

A tool-using model can write "I have recorded your promise" or "I have sent the link" with
no tool call behind it. In collections that is a false statement to a borrower. Kisht stops
it in three places, and this module counts each one from the records, so the weakness and
the guard are both numbers:

  asked again   code saw the claim (or "let me check") with no tool behind it and asked the
                model once more before anything was said;
  replaced      the model claimed again, so its reply was replaced by a safe line;
  reached       a claim with nothing behind it that the borrower did hear. Found afterwards by
                running today's claim patterns over every reply that went out. Old runs can
                have some: the patterns were narrower then.

It also counts the opposite: a payment link sent without the reply saying so.

The same counts split a pass rate in two: runs that passed with no such attempt, and runs
that passed only because code caught one. A run that passed although a false claim reached
the borrower is what the literature calls a corrupt success.

Limits, stated plainly: the detector is pattern-based (the same patterns the live guard
uses), so a claim worded in a way no pattern knows is missed here exactly as it is missed
live. "Asked again" events are logged per conversation, not per turn.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from kisht.confirm import (
    claims_link_sent,
    claims_payment_received,
    claims_promise_saved,
    claims_waiver,
    is_stall,
)

# why code asked the model again -> the kind of claim
RETRY_KIND = {"unbacked_claim_retry": "link", "false_claim_retry": "promise",
              "stall_retry": "stall"}
# why code replaced a reply -> the kind of claim
BLOCK_KIND = {"unbacked_link_claim": "link", "false_promise_claim": "promise",
              "false_claim": "waiver_or_payment"}
KINDS = ("promise", "link", "waiver_or_payment", "stall")
# The runs the published numbers come from: the full suite, and the Tamil/Telugu suite.
PUBLISHED_RUNS = ("local-qwen3.5-9b-v2", "south-qwen3.5-9b-v2")
KIND_WORDS = {"promise": "\"Your promise is saved\"", "link": "\"I have sent the link\"",
              "waiver_or_payment": "\"It is waived\" / \"payment received\"",
              "stall": "\"Let me check / I am recording it\", then nothing"}


def reached_borrower(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Claims in replies that went out with nothing behind them, and links sent silently."""
    out = []
    promise_saved = link_sent = False
    for i, t in enumerate(turns):
        tools = t.get("tools") or []
        replaced = t.get("replaced") or []
        text = t.get("agent") or ""
        promise_saved = promise_saved or bool(t.get("promise_saved"))
        sent_now = "send_payment_link" in tools and not (t.get("refused") or [])
        link_sent = link_sent or "send_payment_link" in tools
        if replaced:                       # the borrower heard code's safe line, not the model
            continue
        # One label per reply, the most serious first.
        kind = None
        if claims_promise_saved(text) and not promise_saved:
            kind = "promise"
        elif claims_link_sent(text) and not link_sent:
            kind = "link"
        elif claims_waiver(text) or claims_payment_received(text):
            kind = "waiver_or_payment"
        elif is_stall(text) and not tools:
            kind = "stall"          # "one moment, let me check", and then nothing happened
        if kind:
            out.append({"turn": i, "kind": kind, "said": text[:200]})
        if sent_now and "link" not in text.lower() and "லிங்க்" not in text and "లింక్" not in text:
            out.append({"turn": i, "kind": "silent_link", "said": text[:200]})
    return out


def measure(conversation: dict[str, Any]) -> dict[str, Any]:
    """One conversation -> its counts. `conversation` has turns (agent, tools, refused,
    replaced, promise_saved) and retries ({audit action: count})."""
    turns = conversation.get("turns") or []
    retried = Counter()
    for action, n in (conversation.get("retries") or {}).items():
        if action in RETRY_KIND:
            retried[RETRY_KIND[action]] += n
    replaced = Counter(BLOCK_KIND[c] for t in turns for c in (t.get("replaced") or [])
                       if c in BLOCK_KIND)
    heard = reached_borrower(turns)
    reached = Counter(h["kind"] for h in heard if h["kind"] != "silent_link")
    # A replaced reply usually followed an "asked again" for the same kind; where the old
    # code had no retry for a kind, the replacement is the only trace of the attempt.
    # A stall that reached the borrower was first asked again, so it is already in `retried`.
    attempts = Counter({k: max(retried[k], replaced[k]) + (0 if k == "stall" else reached[k])
                        for k in KINDS})
    attempts["stall"] = max(attempts["stall"], reached["stall"])
    return {"turns": len(turns), "attempts": attempts, "asked_again": retried,
            "replaced": replaced, "reached": reached, "heard": heard,
            "silent_links": sum(1 for h in heard if h["kind"] == "silent_link")}


def summarise(conversations: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts per language and overall, plus the pass rate split by what code had to catch."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in conversations:
        m = measure(c)
        m["passed"] = c.get("passed")
        m["id"] = c.get("id")
        groups[c.get("language") or "unknown"].append(m)
        groups["all"].append(m)
    out: dict[str, Any] = {}
    for lang, ms in groups.items():
        turns = sum(m["turns"] for m in ms)
        attempts = sum((m["attempts"] for m in ms), Counter())
        reached = sum((m["reached"] for m in ms), Counter())
        replaced = sum((m["replaced"] for m in ms), Counter())
        total = sum(attempts.values())
        row: dict[str, Any] = {
            "conversations": len(ms), "turns": turns,
            "attempts": total, "per_100_turns": _rate(total, turns),
            "conversations_with_attempt": sum(1 for m in ms if sum(m["attempts"].values())),
            "by_kind": {k: attempts[k] for k in KINDS if attempts[k]},
            "replaced": sum(replaced.values()),
            "fixed_by_asking_again": max(0, total - sum(replaced.values())
                                         - sum(reached.values())),
            "reached_borrower": sum(reached.values()),
            "silent_links": sum(m["silent_links"] for m in ms),
            "examples": [dict(h, id=m["id"]) for m in ms for h in m["heard"]
                         if h["kind"] != "silent_link"][:8],
        }
        graded = [m for m in ms if m["passed"] is not None]
        if graded:
            passed = [m for m in graded if m["passed"]]
            clean = [m for m in passed if not sum(m["attempts"].values())]
            corrupt = [m for m in passed if sum(m["reached"].values())]
            row["pass"] = {
                "runs": len(graded), "passed": len(passed),
                "pass_pct": _rate(len(passed), len(graded)),
                "passed_clean": len(clean), "clean_pct": _rate(len(clean), len(graded)),
                "passed_because_code_caught_it": len(passed) - len(clean) - len(corrupt),
                "passed_with_false_claim_heard": len(corrupt),
                "strict_pct": _rate(len(passed) - len(corrupt), len(graded)),
            }
        out[lang] = row
    return out


def _rate(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


# ---------- where the conversations come from ----------

def from_eval_run(run_dir: str | Path, personas_path: str | Path = "evals/personas.yaml"
                  ) -> list[dict[str, Any]]:
    from kisht.evals import load_personas

    language = {p.id: p.language for p in load_personas(str(personas_path))}
    out = []
    with open(Path(run_dir) / "runs.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            actions = (r.get("telemetry") or {}).get("actions") or {}
            out.append({"id": f"{r['persona']}#{r.get('trial', 0)}",
                        "language": language.get(r["persona"], "unknown"),
                        "turns": r.get("turns") or [], "passed": r.get("passed"),
                        "retries": {a: sum(v.values()) for a, v in actions.items()
                                    if a in RETRY_KIND}})
    return out


def from_call_log(insights: Any, audit_dir: str | Path) -> list[dict[str, Any]]:
    retries: dict[str, Counter] = defaultdict(Counter)
    for path in sorted(Path(audit_dir).glob("*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if "_retry" not in line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("action") in RETRY_KIND and e.get("call_id"):
                    retries[e["call_id"]][e["action"]] += 1
    out = []
    for c in insights.calls(limit=10_000):
        turns = [t for t in insights.turns(c["call_id"]) if t["borrower"]]
        saved = "promise" in (c.get("outcome") or "")
        for t in turns:                   # the call log has no per-turn "saved" flag
            t["promise_saved"] = saved and "note" in (t["agent"] or "").lower()[:40] or (
                saved and t is turns[-1])
        out.append({"id": c["call_id"], "language": c.get("language"), "turns": turns,
                    "retries": dict(retries.get(c["call_id"], {}))})
    return out


def render(title: str, s: dict[str, Any]) -> str:
    lines = [title, "",
             ("| Language | Conversations | Agent turns | Claims with nothing behind them | "
             "per 100 turns | Fixed by asking again | Replaced by code | Reached the borrower |"),
             "|---|---|---|---|---|---|---|---|"]
    for lang in sorted(s, key=lambda k: (k == "all", k)):
        r = s[lang]
        lines.append(f"| {lang} | {r['conversations']} | {r['turns']} | {r['attempts']} | "
                     f"{r['per_100_turns']} | {r['fixed_by_asking_again']} | {r['replaced']} | "
                     f"{r['reached_borrower']} |")
    p = s.get("all", {}).get("pass")
    if p:
        lines += ["", (f"Pass rate {p['pass_pct']}% ({p['passed']} of {p['runs']}): "
                      f"{p['passed_clean']} passed with no such attempt ({p['clean_pct']}%), "
                      f"{p['passed_because_code_caught_it']} passed because code caught one, "
                      f"{p['passed_with_false_claim_heard']} passed although a false claim "
                      f"reached the borrower. Counting those as failures: {p['strict_pct']}%.")]
    return "\n".join(lines)
