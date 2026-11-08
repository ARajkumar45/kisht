"""M3: does the stable prompt prefix (D36) actually get cached on the local model server?

    uv run python tools/measure_caching.py            # full run, ~5 min
    uv run python tools/measure_caching.py --quick    # 1 call, 3 turns per condition

A fixed 6-turn salon conversation is replayed; at each turn the model is asked for the
next reply. Three conditions change only the first characters of the system message:

  stable    the normal prefix                 -> cache reuse across turns AND calls
  per-call  "[call <id>] " + prefix           -> reuse across turns of one call only
  none      "[<timestamp>] " + prefix         -> no reuse at all

Then a small interleaving test: salon requests alternating with another business's
requests, to see whether the server keeps more than one prefix cached (matters for
cache-aware routing, D37).

Every request streams, so one request gives time-to-first-token (TTFT), total time,
prompt tokens and cached tokens. Raw rows go to results/m3_caching.csv; the tables are
printed as markdown for docs/RESULTS.md.
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import openai

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from receptionist.business import load_business
from receptionist.prompt import build_messages
from receptionist.tools import TOOL_SCHEMAS

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 11, 9)  # fixed so the calendar line never changes between runs
PROMPT_ONLY = 1            # max_tokens=1: the time measured is prompt processing alone
GEN_TOKENS = 64            # one extra request measures generation speed

# Fixed conversation: user line, then the agent line that "was said" before the next turn.
CONVERSATION = [
    ("Hi, what are your timings on Saturday?",
     "We're open 9 AM to 9 PM on Saturday."),
    ("Kitne ka hai men's haircut?",
     "Men's haircut Rs 300 ka hai, 30 minute lagte hain."),
    ("Kal 11 baje slot hai kya?",
     "Kal 11 baje Ravi ke paas slot free hai. Aapka naam aur phone number bata dijiye?"),
    ("Priya, 9845012345",
     ("Men's haircut with Ravi on Tuesday 10 November at 11:00 AM, for Priya, "
      "phone ending 2345. Shall I book it?")),
    ("Ek minute, is there parking?",
     "Two-wheeler parking in front; cars park on the side road."),
    ("Theek hai, book kar do.", None),
]


@dataclass
class Row:
    experiment: str
    condition: str
    call: int
    turn: int
    prompt_tokens: int
    cached_tokens: int
    completion_tokens: int
    ttft_s: float
    total_s: float


def notebook_at(turn: int, greeting: str) -> list[dict]:
    """Greeting + the first `turn` user lines (and the agent lines between them)."""
    msgs = [{"role": "assistant", "content": greeting}]
    for i, (user, agent) in enumerate(CONVERSATION[:turn]):
        msgs.append({"role": "user", "content": user})
        if i < turn - 1 and agent:
            msgs.append({"role": "assistant", "content": agent})
    return msgs


def with_prefix(messages: list[dict], marker: str) -> list[dict]:
    system = dict(messages[0])
    system["content"] = marker + system["content"]
    return [system, *messages[1:]]


class Runner:
    def __init__(self, base_url: str, model: str):
        self.client = openai.OpenAI(base_url=base_url, api_key="local", timeout=120)
        self.model = model

    def measure(self, messages: list[dict],
                max_tokens: int = PROMPT_ONLY) -> tuple[int, int, int, float, float]:
        started = time.perf_counter()
        first = None
        usage = None
        stream = self.client.chat.completions.create(
            model=self.model, messages=messages, tools=TOOL_SCHEMAS, max_tokens=max_tokens,
            temperature=0.0, stream=True, stream_options={"include_usage": True},
            extra_body={"chat_template_kwargs": {"enable_thinking": False}})
        for chunk in stream:
            if chunk.choices and first is None:
                delta = chunk.choices[0].delta
                if delta.content or delta.tool_calls:
                    first = time.perf_counter() - started
            if chunk.usage:
                usage = chunk.usage
        total = time.perf_counter() - started
        if first is None:
            first = total
        details = getattr(usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) or 0
        return usage.prompt_tokens, cached, usage.completion_tokens or 0, first, total


def run_conditions(runner: Runner, business, calls: int, turns: int) -> list[Row]:
    base = [build_messages(business, notebook_at(t, business.greeting["en"]), TODAY)
            for t in range(1, turns + 1)]
    rows: list[Row] = []
    # Warm-up with a unique prefix, so the first measured request is not also waking the GPU.
    runner.measure(with_prefix(base[0], f"[warmup {time.time_ns()}] "))
    for condition in ("stable", "per-call", "none"):
        for call in range(1, calls + 1):
            call_marker = f"[call {uuid.uuid4().hex[:8]}] "
            for turn, messages in enumerate(base, start=1):
                if condition == "per-call":
                    messages = with_prefix(messages, call_marker)
                elif condition == "none":
                    messages = with_prefix(messages, f"[{time.time_ns()}] ")
                p, c, comp, ttft, total = runner.measure(messages)
                rows.append(Row("conditions", condition, call, turn, p, c, comp, ttft, total))
                print(f"  {condition:8} call {call} turn {turn}: prompt {p:5} cached {c:5} "
                      f"prompt time {total:5.2f}s", flush=True)
    return rows


def run_cold_start(runner: Runner, business) -> list[Row]:
    """A business the server has never seen (random name): first request is a true cold
    start; the second shows what one warm-up buys. The salon itself is never cold here,
    because the server has cached its prefix since M2 (it keeps several prompt caches)."""
    fresh = business.model_copy(update={"business_id": "fresh", "name": f"Salon {uuid.uuid4().hex[:6]}"})
    messages = build_messages(fresh, notebook_at(1, fresh.greeting["en"]), TODAY)
    rows: list[Row] = []
    for attempt, label in ((1, "cold"), (2, "warm")):
        p, c, comp, ttft, total = runner.measure(messages)
        rows.append(Row("cold_start", label, 1, attempt, p, c, comp, ttft, total))
        print(f"  cold start, {label:4}: prompt {p:5} cached {c:5} prompt time {total:5.2f}s",
              flush=True)
    return rows


def run_interleaved(runner: Runner, business, other, turns: int) -> list[Row]:
    """Salon turn, other-business turn, salon turn, ... Does the salon prefix stay cached?"""
    rows: list[Row] = []
    for turn in range(1, turns + 1):
        for name, biz in (("salon", business), ("other", other)):
            messages = build_messages(biz, notebook_at(turn, biz.greeting["en"]), TODAY)
            p, c, comp, ttft, total = runner.measure(messages)
            rows.append(Row("interleaved", name, 1, turn, p, c, comp, ttft, total))
            print(f"  interleaved {name:5} turn {turn}: prompt {p:5} cached {c:5} "
                  f"prompt time {total:5.2f}s", flush=True)
    return rows


def median(values) -> float:
    values = list(values)
    return statistics.median(values) if values else float("nan")


def summarize(rows: list[Row]) -> str:
    """Markdown tables for docs/RESULTS.md."""
    out = [("| Condition | Requests | Median prompt time | Slowest | Cached share | "
            "Uncached prompt tokens/s |"), "|---|---|---|---|---|---|"]
    for cond in ("stable", "per-call", "none"):
        rs = [r for r in rows if r.experiment == "conditions" and r.condition == cond]
        if not rs:
            continue
        share = sum(r.cached_tokens for r in rs) / max(1, sum(r.prompt_tokens for r in rs))
        speed = median((r.prompt_tokens - r.cached_tokens) / r.ttft_s
                       for r in rs if r.prompt_tokens - r.cached_tokens > 100)
        speed_txt = "n/a (almost all cached)" if math.isnan(speed) else f"{speed:,.0f}"
        out.append(f"| {cond} | {len(rs)} | {median(r.ttft_s for r in rs):.2f} s | "
                   f"{max(r.total_s for r in rs):.2f} s | {share:.0%} | {speed_txt} |")

    cold = [r for r in rows if r.experiment == "cold_start"]
    first = [r for r in rows if r.experiment == "conditions" and r.condition == "stable"
             and r.turn == 1]
    if cold or first:
        out += ["", "First turn of a call (what a new caller waits for):", "",
                "| Case | Prompt tokens | Cached | Prompt time |", "|---|---|---|---|"]
        for r in cold:
            case = ("never-seen business, first request (cold)" if r.condition == "cold"
                    else "same business, second request (warm)")
            out.append(f"| {case} | {r.prompt_tokens} | {r.cached_tokens} | {r.total_s:.2f} s |")
        for r in first:
            out.append(f"| salon, call {r.call} (prefix cached since earlier calls) | "
                       f"{r.prompt_tokens} | {r.cached_tokens} | {r.total_s:.2f} s |")

    inter = [r for r in rows if r.experiment == "interleaved"]
    if inter:
        out += ["", "Interleaved calls to two businesses (salon, other, salon, other, ...):", "",
                "| Turn | Business | Prompt tokens | Cached | Prompt time |", "|---|---|---|---|---|"]
        for r in inter:
            out.append(f"| {r.turn} | {r.condition} | {r.prompt_tokens} | {r.cached_tokens} | "
                       f"{r.ttft_s:.2f} s |")
    return "\n".join(out)


def other_business(business):
    """Same template, different name and address: a second tenant with its own prefix."""
    return business.model_copy(update={"business_id": "other-salon", "name": "Lotus Salon",
                                       "address": "5, 80 Feet Road, Koramangala, Bengaluru"})


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--quick", action="store_true", help="1 call, 3 turns per condition")
    p.add_argument("--calls", type=int, default=3)
    p.add_argument("--turns", type=int, default=len(CONVERSATION))
    p.add_argument("--base-url", default="http://localhost:8080/v1")
    p.add_argument("--model", default="mlx-community/Qwen3.5-9B-4bit")
    p.add_argument("--out", default=str(ROOT / "results" / "m3_caching.csv"))
    args = p.parse_args(argv)
    calls, turns = (1, 3) if args.quick else (args.calls, args.turns)

    business = load_business(ROOT / "businesses" / "glow-salon.yaml")
    runner = Runner(args.base_url, args.model)
    rows = run_conditions(runner, business, calls, turns)
    rows += run_cold_start(runner, business)
    rows += run_interleaved(runner, business, other_business(business), min(turns, 3))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()))
        writer.writeheader()
        writer.writerows(asdict(r) for r in rows)
    print(f"\n{len(rows)} rows -> {out}\n")
    print(summarize(rows))

    # One longer answer on a warm prefix: how fast does the model talk once it starts?
    base = build_messages(business, notebook_at(1, business.greeting["en"]), TODAY)
    _, _, comp, first, total = runner.measure(base, max_tokens=GEN_TOKENS)
    if comp > 1 and total > first:
        print(f"\nGeneration speed (warm prefix, {comp} tokens): "
              f"{comp / (total - first):.0f} tokens/s; first token after {first:.2f} s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
