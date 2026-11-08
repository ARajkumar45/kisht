"""Chat with the receptionist as a caller, in the terminal.

    uv run receptionist chat                       # Glow Salon, local model
    uv run receptionist chat --business glow-salon --lang hi

Commands while chatting: /state  /notebook  /audit  /quit
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from receptionist.audit import AuditLog
from receptionist.bookings import SqliteBookingStore
from receptionist.business import BusinessRegistry, ConfigError
from receptionist.guard import Guard
from receptionist.model_client import OpenAICompatibleClient
from receptionist.notebook import CallStore
from receptionist.session import CallSession

DIM, BOLD, END = "\033[2m", "\033[1m", "\033[0m"


def chat(args: argparse.Namespace) -> int:
    try:
        registry = BusinessRegistry.from_dir(args.businesses_dir)
        business = (registry.by_called_number(args.number) if args.number
                    else registry.by_id(args.business))
    except ConfigError as e:
        print(f"Config problem: {e}", file=sys.stderr)
        return 2

    calls = CallStore.from_url(args.redis_url)
    try:
        calls.r.ping()
    except Exception as e:  # noqa: BLE001 - show any connection problem plainly
        print(f"Cannot reach Redis at {args.redis_url}: {e}\n"
              "Start it with: brew services start redis", file=sys.stderr)
        return 2

    audit = AuditLog(args.audit)
    guard = Guard(business, SqliteBookingStore(args.db), calls, audit)
    model = OpenAICompatibleClient(base_url=args.model_url, model=args.model,
                                   api_key=os.getenv("MODEL_API_KEY", "local"))
    session, greeting = CallSession.start(business, calls, guard, model,
                                          called_number=business.phone_numbers[0],
                                          language=args.lang)
    print(f"{DIM}call {session.call_id} · {business.name} · model {args.model}{END}")
    print(f"{BOLD}agent>{END} {greeting}")

    outcome = "hung_up"
    while True:
        try:
            text = input(f"{BOLD}you>{END} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text == "/quit":
            break
        if text == "/state":
            print(json.dumps(calls.get_state(session.call_id), indent=2, ensure_ascii=False))
            continue
        if text == "/notebook":
            for m in calls.messages(session.call_id):
                print(f"{DIM}{json.dumps(m, ensure_ascii=False)}{END}")
            continue
        if text == "/audit":
            for e in audit.for_call(session.call_id):
                print(f"{DIM}{e['outcome']:6} {e['action']:20} {e['detail']}{END}")
            continue

        turn = session.handle(text)
        print(f"{BOLD}agent>{END} {turn.reply}")
        notes = [f"{turn.model_latency_s:.2f}s", f"{turn.model_calls} model call(s)"]
        if turn.tool_calls:
            notes.append("tools: " + ", ".join(turn.tool_calls))
        if turn.prompt_tokens:
            notes.append(f"prompt {turn.prompt_tokens} tok, cached {turn.cached_tokens}")
        if turn.booked:
            notes.append("BOOKED")
            outcome = "booked"
        if turn.replaced_false_claim:
            notes.append("false booking claim replaced")
        if turn.replaced_unchecked_claim:
            notes.append("unchecked availability replaced")
        if turn.fallback:
            notes.append("fallback")
        print(f"{DIM}  [{' · '.join(notes)}]{END}")

    session.end(outcome)
    print(f"{DIM}call ended: {outcome}{END}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="receptionist")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("chat", help="chat with the agent as a caller")
    c.add_argument("--business", default="glow-salon")
    c.add_argument("--number", help="pick the business by the number called instead")
    c.add_argument("--lang", choices=["en", "hi", "kn", "te", "ta"])
    c.add_argument("--businesses-dir", default="businesses")
    c.add_argument("--redis-url", default=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    c.add_argument("--db", default=os.getenv("BOOKINGS_DB", "data/bookings.sqlite"))
    c.add_argument("--audit", default=os.getenv("AUDIT_LOG", "audit/audit.jsonl"))
    c.add_argument("--model-url", default=os.getenv("MODEL_BASE_URL", "http://localhost:8080/v1"))
    c.add_argument("--model", default=os.getenv("MODEL_NAME", "mlx-community/Qwen3.5-9B-4bit"))
    args = p.parse_args(argv)
    return chat(args)


if __name__ == "__main__":
    raise SystemExit(main())
