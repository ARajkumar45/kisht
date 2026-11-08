"""M4: many simulated callers at once, through the real CallSession (D61, D66).

    uv run python tools/load_test.py --model fake                 # our code's limit
    uv run python tools/load_test.py --model real --budget-s 300  # the Mac's limit

Two model backends behind the same ModelClient protocol:
  fake   InstantModel: replies instantly with the ideal tool flow, so the numbers show
         what session + guard + Redis + SQLite + audit can take on their own.
  real   the local mlx server, the whole system end to end.

Each level starts N callers together; each caller has 4 scripted turns and wants a
different slot (day and time spread over Ravi's free times). Success for a caller is a
booking saved with their phone number. Uses Redis db 1 and a fresh SQLite file per run,
so dev data is never touched.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from receptionist.audit import AuditLog
from receptionist.bookings import SqliteBookingStore
from receptionist.business import WEEKDAYS, Business, load_business
from receptionist.guard import Guard
from receptionist.model_client import ModelReply, OpenAICompatibleClient, ToolCall
from receptionist.notebook import CallStore
from receptionist.session import STUCK, CallSession

ROOT = Path(__file__).resolve().parent.parent
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SERVICE = "haircut-men"
SERVICE_MIN = 30


# ---------- the caller ----------

@dataclass
class CallerScript:
    index: int
    name: str
    phone: str
    day: date
    start: datetime
    lines: list[str]


def caller_scripts(business: Business, count: int, today: date, first_index: int = 0
                   ) -> list[CallerScript]:
    """Spread callers over the next 7 days and over each day's free 30-minute starts."""
    tz = ZoneInfo(business.timezone)
    per_day: dict[date, list[datetime]] = {}
    for offset in range(1, 8):      # next 7 days: a weekday name in the script is unambiguous
        d = today + timedelta(days=offset)
        starts = []
        for open_t, close_t in business.hours.get(WEEKDAYS[d.weekday()], []):
            t = datetime.combine(d, open_t, tz)
            end = datetime.combine(d, close_t, tz)
            while t + timedelta(minutes=SERVICE_MIN) <= end:
                starts.append(t)
                t += timedelta(minutes=SERVICE_MIN)
        per_day[d] = starts
    # Interleave days so consecutive callers land on different days and times:
    # Mon 10:00, Tue 10:00, ... Sun 10:00, Mon 10:30, Tue 10:30, ...
    flat: list[datetime] = []
    for k in range(max(len(v) for v in per_day.values())):
        flat += [starts[k] for starts in per_day.values() if k < len(starts)]
    scripts = []
    for i in range(first_index, first_index + count):
        start = flat[i % len(flat)]
        d = start.date()
        name, phone = f"Caller{i}", f"98450{i:05d}"
        scripts.append(CallerScript(i, name, phone, d, start, [
            (f"{DAY_NAMES[d.weekday()]} ko {start:%H:%M} baje men's haircut chahiye. "
             f"Naam {name}, number {phone}."),
            "haan, book kar do",
            "haan",
            "theek hai, thank you",
        ]))
    return scripts


# ---------- the instant fake model ----------

_LINE = re.compile(r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday) ko "
                   r"(\d{1,2}):(\d{2}) baje.*?naam (\w+), number (\d{10})", re.IGNORECASE)


class InstantModel:
    """Scripted ideal behaviour: check availability, propose, read back. No thinking time."""

    def __init__(self, today: date):
        self.today = today

    def complete(self, messages, tools) -> ModelReply:
        last = messages[-1]
        details = self._details(messages)
        if last["role"] == "tool":
            data = json.loads(last["content"])
            name = self._tool_name(messages, last["tool_call_id"])
            if name == "check_availability":
                slots = data.get("slots") or []
                if not slots or not details:
                    return ModelReply(content="Sorry, there is no free time that day. "
                                              "Another day?")
                wanted = details["start"].strftime("%Y-%m-%dT%H:%M")
                pick = next((s for s in slots if s["start"] == wanted), slots[0])
                return self._call("book_visit", service_id=SERVICE, start=pick["start"],
                                  customer_name=details["name"],
                                  customer_phone=details["phone"])
            if name == "book_visit":
                if data.get("ok"):
                    return ModelReply(content=data["read_back"])
                if details and data.get("refused") in {"slot_taken", "closed", "too_soon",
                                                        "off_grid", "in_past"}:
                    return self._call("check_availability", service_id=SERVICE,
                                      day=details["start"].date().isoformat(),
                                      preferred_time=details["start"].strftime("%H:%M"))
                return ModelReply(content="Sorry, I could not book that. "
                                          + data.get("message", ""))
        text = last.get("content") or ""
        previous = next((m.get("content") or "" for m in reversed(messages[:-1])
                         if m["role"] == "assistant"), "")
        lost_race = previous.startswith(("Sorry, that time was just taken",
                                         "Maaf kijiye, woh time abhi abhi"))
        if details and (_LINE.search(text) or lost_race):
            return self._call("check_availability", service_id=SERVICE,
                              day=details["start"].date().isoformat(),
                              preferred_time=details["start"].strftime("%H:%M"))
        return ModelReply(content="Theek hai, dhanyavaad. Aur kuch?")

    def _details(self, messages):
        for m in messages:
            if m["role"] == "user" and (hit := _LINE.search(m.get("content") or "")):
                day_name, hh, mm, name, phone = hit.groups()
                offset = (DAY_NAMES.index(day_name.capitalize()) - self.today.weekday()) % 7 or 7
                d = self.today + timedelta(days=offset)
                return {"name": name, "phone": phone,
                        "start": datetime(d.year, d.month, d.day, int(hh), int(mm))}
        return None

    @staticmethod
    def _tool_name(messages, tool_call_id):
        for m in reversed(messages):
            for tc in m.get("tool_calls") or []:
                if tc["id"] == tool_call_id:
                    return tc["function"]["name"]
        return ""

    @staticmethod
    def _call(name, **args) -> ModelReply:
        return ModelReply(content="", tool_calls=[ToolCall(f"call_{name}_{time.time_ns()}",
                                                           name, json.dumps(args))])


# ---------- the run ----------

@dataclass
class TurnRow:
    model: str
    level: int
    caller: int
    turn: int
    latency_s: float
    model_calls: int
    tool_calls: str
    prompt_tokens: int
    cached_tokens: int
    booked: bool
    fallback: bool
    stuck: bool
    replaced: bool
    error: str = ""


def run_caller(script: CallerScript, business, calls, guard, model, model_name: str,
               level: int, deadline: float) -> list[TurnRow]:
    rows = []
    try:
        session, _ = CallSession.start(business, calls, guard, model)
    except Exception as e:  # noqa: BLE001 - a failure to even start a call is a result
        return [TurnRow(model_name, level, script.index, 0, 0, 0, "", 0, 0, False, False,
                        False, False, f"start: {type(e).__name__}: {e}"[:200])]
    for turn, line in enumerate(script.lines, start=1):
        if time.monotonic() > deadline:
            rows.append(TurnRow(model_name, level, script.index, turn, 0, 0, "", 0, 0, False,
                                False, False, False, "budget exceeded"))
            break
        started = time.perf_counter()
        try:
            t = session.handle(line)
        except Exception as e:  # noqa: BLE001
            rows.append(TurnRow(model_name, level, script.index, turn,
                                time.perf_counter() - started, 0, "", 0, 0, False, False,
                                False, False, f"{type(e).__name__}: {e}"[:200]))
            continue
        rows.append(TurnRow(model_name, level, script.index, turn, time.perf_counter() - started,
                            t.model_calls, "+".join(t.tool_calls), t.prompt_tokens,
                            t.cached_tokens, t.booked, t.fallback,
                            t.reply in STUCK.values(),
                            t.replaced_false_claim or t.replaced_unchecked_claim))
        if t.booked:
            break           # the caller got what they came for
    session.end("booked" if any(r.booked for r in rows) else "hung_up")
    return rows


def run_level(level, business, calls, guard, model, model_name, budget_s, first_index, today):
    scripts = caller_scripts(business, level, today, first_index)
    deadline = time.monotonic() + budget_s
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=level) as pool:
        results = list(pool.map(lambda s: run_caller(s, business, calls, guard, model,
                                                     model_name, level, deadline), scripts))
    wall = time.perf_counter() - started
    rows = [r for rs in results for r in rs]
    return rows, wall


def percentile(values, p):
    values = sorted(values)
    if not values:
        return float("nan")
    k = max(0, min(len(values) - 1, round(p / 100 * (len(values) - 1))))
    return values[k]


def summarize(rows: list[TurnRow], walls: dict[int, float]) -> str:
    out = [("| Callers at once | Bookings made | Median turn | p95 turn | Turns/min | "
            "Fallbacks | Stuck | Errors | Cached share | Wall time |"),
           "|---|---|---|---|---|---|---|---|---|---|"]
    for level in sorted({r.level for r in rows}):
        rs = [r for r in rows if r.level == level]
        ok = [r for r in rs if not r.error]
        callers = {r.caller for r in rs}
        booked = len({r.caller for r in rs if r.booked})
        lat = [r.latency_s for r in ok]
        wall = walls.get(level, 0) or 1e-9
        prompt = sum(r.prompt_tokens for r in ok)
        share = f"{sum(r.cached_tokens for r in ok) / prompt:.0%}" if prompt else "n/a"
        out.append(f"| {level} | {booked}/{len(callers)} | "
                   f"{statistics.median(lat) if lat else float('nan'):.2f} s | "
                   f"{percentile(lat, 95):.2f} s | {60 * len(ok) / wall:.0f} | "
                   f"{sum(r.fallback for r in ok)}/{len(ok)} | {sum(r.stuck for r in ok)} | "
                   f"{len(rs) - len(ok)} | {share} | {wall:.1f} s |")
    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model", choices=["fake", "real"], default="fake")
    p.add_argument("--levels", default="1,10,50,100")
    p.add_argument("--budget-s", type=float, default=300)
    p.add_argument("--timeout-s", type=float, default=30,
                   help="model request timeout (the session default is 30 s)")
    p.add_argument("--note", default="", help="free text recorded in the CSV name, e.g. server flags")
    p.add_argument("--redis-url", default="redis://localhost:6379/1")
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)
    levels = [int(x) for x in args.levels.split(",")]

    business = load_business(ROOT / "businesses" / "glow-salon.yaml")
    tz = ZoneInfo(business.timezone)
    today = datetime.now(tz).date()
    calls = CallStore.from_url(args.redis_url)
    calls.r.flushdb()
    run_id = time.strftime("%Y%m%d_%H%M%S")
    audit = AuditLog(ROOT / "audit" / f"load_{args.model}_{run_id}.jsonl")
    model = (InstantModel(today) if args.model == "fake"
             else OpenAICompatibleClient(timeout_s=args.timeout_s))

    rows: list[TurnRow] = []
    walls: dict[int, float] = {}
    for level in levels:
        # Each level is its own experiment: a fresh schedule, callers numbered from 0,
        # so every caller at a level wants a different free slot (132 exist, max level 100).
        db = ROOT / "data" / f"load_{args.model}_{run_id}_{level}.sqlite"
        guard = Guard(business, SqliteBookingStore(db), calls, audit)
        print(f"\n== {args.model} model, {level} callers at once", flush=True)
        level_rows, wall = run_level(level, business, calls, guard, model, args.model,
                                     args.budget_s, 0, today)
        rows += level_rows
        walls[level] = wall
        print(summarize(level_rows, {level: wall}).splitlines()[-1], flush=True)

    suffix = f"_{args.note}" if args.note else ""
    out = Path(args.out or ROOT / "results" / f"m4_load_{args.model}{suffix}.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()))
        w.writeheader()
        w.writerows(asdict(r) for r in rows)
    print(f"\n{len(rows)} turn rows -> {out}\n")
    print(summarize(rows, walls))
    errors = [r.error for r in rows if r.error]
    if errors:
        print("\nErrors (first 5 distinct):")
        for e in list(dict.fromkeys(errors))[:5]:
            print("  -", e)
    return 0


if __name__ == "__main__":
    threading.stack_size(512 * 1024)
    raise SystemExit(main())
