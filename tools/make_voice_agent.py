"""Create a Bolna voice agent that calls one borrower through the Kisht voice bridge.

    uv run python tools/make_voice_agent.py br_0009              # writes bolna/kisht-br_0009.json
    uv run python tools/make_voice_agent.py br_0009 --post       # and creates it in local Bolna

The agent's welcome message is exactly our greeting for that borrower (Bolna speaks it; our
transcript already holds it), its LLM is the bridge, and its `model` names lender and borrower.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

from kisht.agent import greeting_for
from kisht.config import load_config
from kisht.languages import pack
from kisht.ledger import SqliteLedger
from kisht.lender import LenderRegistry

ROOT = Path(__file__).resolve().parent.parent
IDS = ROOT / "data" / "bolna_agents.json"


def config_for(lender, borrower: dict, bridge_url: str, speech) -> dict:
    lang = borrower["language"] if borrower["language"] in lender.languages.allowed \
        else lender.languages.default
    greeting = greeting_for(lender, lang, borrower["name"].split()[0], "voice")
    sarvam_lang = pack(lang).sarvam
    # Hindi callers mix in English, which Sarvam's en-IN mode transcribes best (D84); Tamil
    # and Telugu need their own language code to be recognised at all.
    stt_lang = "en-IN" if lang in ("en", "hi") else sarvam_lang
    return {"agent_config": {
        "agent_name": f"Kisht {lender.id} -> {borrower['id']} (mic)",
        "agent_type": "other",
        "tasks": [{"task_type": "conversation",
                   "toolchain": {"execution": "parallel",
                                 "pipelines": [["transcriber", "llm", "synthesizer"]]},
                   "tools_config": {
                       "input": {"provider": "default", "format": "pcm"},
                       "output": {"provider": "default", "format": "pcm"},
                       "transcriber": {"provider": "sarvam", "model": speech.stt_model,
                                       "language": stt_lang, "stream": True,
                                       "encoding": "linear16", "endpointing": 400,
                                       "high_vad_sensitivity": False},
                       "llm_agent": {"agent_type": "simple_llm_agent",
                                     "agent_flow_type": "streaming",
                                     "llm_config": {"provider": "custom",
                                                    "model": f"{lender.id}:{borrower['id']}",
                                                    "base_url": bridge_url, "max_tokens": 400,
                                                    "temperature": 0.3}},
                       "synthesizer": {"provider": "sarvam", "stream": True,
                                       "audio_format": "linear16",
                                       "provider_config": {"voice": speech.speaker,
                                                           "voice_id": speech.speaker,
                                                           "model": speech.tts_model,
                                                           "language": sarvam_lang},
                                       "buffer_size": 40.0, "caching": True}},
                   "task_config": {"hangup_after_silence": 30.0, "use_fillers": False,
                                   "optimize_latency": False,
                                   "number_of_words_for_interruption": 2,
                                   "backchanneling": False, "incremental_delay": 1500,
                                   "check_if_user_online": False}}],
        "agent_welcome_message": greeting},
        "agent_prompts": {"task_1": {"system_prompt": (
            "Unused: every reply comes from the Kisht agent behind the custom LLM endpoint.")}}}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("borrower")
    p.add_argument("--lender", default="demo-nbfc")
    p.add_argument("--bridge", default="http://localhost:5050/v1")
    p.add_argument("--post", action="store_true")
    p.add_argument("--bolna", default="http://localhost:5001")
    a = p.parse_args(argv)
    cfg = load_config()
    lender = LenderRegistry.from_dir(cfg.lenders_dir).get(a.lender)
    borrower = SqliteLedger(cfg.stores.ledger_db).borrower(a.borrower)
    if not borrower:
        print(f"no borrower {a.borrower} (run tools/make_loan_book.py)", file=sys.stderr)
        return 2
    out = ROOT / "bolna" / f"kisht-{a.borrower}.json"
    out.write_text(json.dumps(config_for(lender, borrower, a.bridge, cfg.speech), indent=2,
                              ensure_ascii=False))
    print(f"wrote {out.relative_to(ROOT)}")
    if a.post:
        r = httpx.post(f"{a.bolna}/agent", json=json.loads(out.read_text()), timeout=30)
        r.raise_for_status()
        agent_id = r.json().get("agent_id")
        ids = json.loads(IDS.read_text()) if IDS.exists() else {}
        ids[out.name] = agent_id
        IDS.write_text(json.dumps(ids, indent=2) + "\n")
        print(f"Bolna agent {agent_id}")
    try:
        # Have the model read this borrower's instructions now, so the first reply of the
        # call is fast. Run this script (or POST /prepare yourself) again just before dialling:
        # the model server remembers only the last few borrowers.
        root = a.bridge.removesuffix("/v1")
        httpx.post(f"{root}/prepare", json={"model": f"{a.lender}:{a.borrower}"},
                   timeout=5).raise_for_status()
        print("bridge is preparing this call")
    except httpx.HTTPError:
        print("bridge not reachable: the first reply of the call will be slow (about 5 s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
