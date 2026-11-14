"""Run the evals. Resumable: finished runs are kept in runs.jsonl and skipped next time.

    uv run python evals/run.py --k 4                         # all personas, 4 runs each
    uv run python evals/run.py --k 1 --only promise,hardship # some categories or persona ids
    uv run python evals/run.py --k 4 --out results/evals/local-qwen9b --workers 2
    uv run python evals/run.py --smoke --k 2                 # 8 personas, the fast gate
    uv run python evals/run.py --personas evals/personas_heldout.yaml   # never used for tuning

Models come from config.yaml roles `agent` and `simulator`; switch them there.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fakeredis

from kisht.adapters.call_state import RedisCallState
from kisht.config import LLMFactory, load_config
from kisht.evals import SMOKE, dumps, grade, load_personas, quality, simulate, summarise
from kisht.knowledge import Agreement
from kisht.lender import LenderRegistry


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--k", type=int, default=4)
    p.add_argument("--only", default="", help="comma-separated persona ids or categories")
    p.add_argument("--out", default="results/evals/latest")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--personas", default="evals/personas.yaml")
    p.add_argument("--smoke", action="store_true",
                   help="only the 8 smoke personas (one per kind of conversation)")
    p.add_argument("--min-pass", type=float, default=None,
                   help="exit 1 if pass^1 is below this (for a CI gate), e.g. 0.6")
    a = p.parse_args(argv)

    cfg = load_config(a.config)
    lender = LenderRegistry.from_dir(cfg.lenders_dir).get("demo-nbfc")
    agreement = Agreement.load(f"{cfg.knowledge_dir}/{lender.id}.yaml")
    factory = LLMFactory(cfg)
    agent_model, sim_model = factory.for_role("agent"), factory.for_role("simulator")
    personas = load_personas(a.personas)
    if a.smoke:
        personas = [x for x in personas if x.id in SMOKE]
    if a.only:
        want = set(a.only.split(","))
        personas = [x for x in personas if x.id in want or x.category in want]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    runs_file = out / "runs.jsonl"
    done = set()
    if runs_file.exists():
        for line in runs_file.read_text().splitlines():
            r = json.loads(line)
            done.add((r["persona"], r["trial"]))
    todo = [(x, t) for x in personas for t in range(a.k) if (x.id, t) not in done]
    print(f"{len(personas)} personas x {a.k} runs: {len(done)} already done, {len(todo)} to go. "
          f"agent={agent_model.name} simulator={sim_model.name}", flush=True)
    lock = threading.Lock()

    def one(item):
        persona, trial = item
        calls = RedisCallState(fakeredis.FakeRedis(decode_responses=True))
        run = simulate(persona, lender=lender, agent_model=agent_model,
                       simulator_model=sim_model, calls=calls, agreement=agreement)
        checks = grade(run, persona.expect, lender)
        q = quality(run, lender)
        row = {**run, "trial": trial, "checks": checks, "passed": all(checks.values()),
               "quality": q, "clean": all(checks.values()) and all(q.values()),
               "agent_model": agent_model.name, "simulator_model": sim_model.name}
        with lock:
            with open(runs_file, "a", encoding="utf-8") as f:
                f.write(dumps(row) + "\n")
            failed = [c for c, ok in {**checks, **q}.items() if not ok]
            verdict = "CLEAN" if row["clean"] else "PASS " if row["passed"] else "FAIL "
            print(f"{verdict} {persona.id:26} #{trial} "
                  f"{len(run['turns'])} turns {run['seconds']:>6.1f}s outcome={run['outcome']}"
                  + (f"  failed: {', '.join(failed)}" if failed else ""), flush=True)

    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        list(pool.map(one, todo))

    rows = [json.loads(line) for line in runs_file.read_text().splitlines()]
    rows = [r for r in rows if any(r["persona"] == x.id for x in personas)]
    s = summarise(rows, a.k)
    (out / "summary.json").write_text(json.dumps(s.as_dict(), indent=2))
    lines = [f"# Eval summary ({out.name})", "",
             (f"agent `{rows[0]['agent_model']}`, simulator `{rows[0]['simulator_model']}`; "
              f"{s.personas} personas, {s.runs} runs, k={s.k}"), "",
             (f"**pass^1 = {s.pass_1:.2f}**, **pass^{s.k} = {s.pass_k:.2f}**, "
              f"median turn {s.median_turn_s:.1f} s, errors {s.errors}"), "",
             (f"pass^1 95% interval {s.pass_1_interval[0]:.2f} to {s.pass_1_interval[1]:.2f} "
              f"(whole personas resampled). **Clean = {s.clean_1:.2f}**: passed, and at most "
              "one reply replaced by code, no reply in the wrong language, no repeated reply, "
              "not cut off by the turn limit."), "",
             f"| Category | Personas | pass^1 | pass^{s.k} |", "|---|---|---|---|"]
    for cat, v in s.by_category.items():
        lines.append(f"| {cat} | {v['personas']} | {v['pass_1']:.2f} | {v[f'pass_{s.k}']:.2f} |")
    lines += ["", f"Failed checks: {s.failed_checks}",
              f"Failed quality checks: {s.failed_quality}", f"Guard blocks: {s.guard_blocks}",
              f"Replies replaced by code: {s.replaced}"]
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    if a.min_pass is not None and s.pass_1 < a.min_pass:
        print(f"pass^1 {s.pass_1:.2f} is below --min-pass {a.min_pass:.2f}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
