"""Create (or re-create) a Bolna agent from a config in bolna/ and remember its id.

    uv run python tools/bolna_agent.py bolna/glow-salon-mic.json
    uv run python tools/bolna_agent.py bolna/glow-salon-twilio.json --bolna http://localhost:5001

Bolna keeps agents in Redis without persistence in Docker, and the welcome message in the
config must match the business greeting, so this checks that before posting. Ids are saved
to data/bolna_agents.json as {config file name: agent id}.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
IDS = ROOT / "data" / "bolna_agents.json"


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("config")
    p.add_argument("--bolna", default="http://localhost:5001")
    args = p.parse_args(argv)

    cfg = json.loads(Path(args.config).read_text())
    llm = cfg["agent_config"]["tasks"][0]["tools_config"]["llm_agent"]["llm_config"]
    business_id = llm["model"]
    biz = yaml.safe_load((ROOT / "businesses" / f"{business_id}.yaml").read_text())
    greeting = biz["greeting"][biz["languages"]["default"]]
    if cfg["agent_config"]["agent_welcome_message"] != greeting:
        print(f"welcome message differs from businesses/{business_id}.yaml greeting:\n"
              f"  agent:    {cfg['agent_config']['agent_welcome_message']}\n"
              f"  business: {greeting}", file=sys.stderr)
        return 2

    r = httpx.post(f"{args.bolna}/agent", json=cfg, timeout=30)
    r.raise_for_status()
    agent_id = r.json()["agent_id"]
    IDS.parent.mkdir(exist_ok=True)
    ids = json.loads(IDS.read_text()) if IDS.exists() else {}
    ids[Path(args.config).name] = agent_id
    IDS.write_text(json.dumps(ids, indent=2) + "\n")
    print(agent_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
