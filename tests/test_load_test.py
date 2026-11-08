"""The M4 load-test pieces that need no server."""
import importlib.util
import sys
from datetime import date
from pathlib import Path

import fakeredis

from receptionist.audit import AuditLog
from receptionist.bookings import SqliteBookingStore
from receptionist.guard import Guard
from receptionist.notebook import CallStore

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "load_test.py"
spec = importlib.util.spec_from_file_location("load_test", SCRIPT)
lt = importlib.util.module_from_spec(spec)
sys.modules["load_test"] = lt
spec.loader.exec_module(lt)

TODAY = date(2026, 11, 8)   # Sunday


def test_callers_want_different_slots_on_different_days(salon):
    scripts = lt.caller_scripts(salon, 100, TODAY)
    assert len({(s.day, s.start) for s in scripts}) == 100       # no two want the same slot
    assert len({s.day for s in scripts}) == 7
    assert all(s.start.date() > TODAY for s in scripts)
    assert scripts[0].lines[0].startswith("Monday ko 10:00 baje men's haircut chahiye. Naam Caller0")
    assert len({s.phone for s in scripts}) == 100


def test_instant_model_follows_the_ideal_flow(salon, clock):
    """One caller end to end with the fake model: check -> propose -> read-back -> yes -> booked."""
    today = clock["now"].date()                                 # Monday 2026-11-09
    guard = Guard(salon, SqliteBookingStore(),
                  CallStore(fakeredis.FakeRedis(decode_responses=True)), AuditLog(),
                  now=lambda: clock["now"])
    script = lt.caller_scripts(salon, 1, today)[0]
    rows = lt.run_caller(script, salon, guard.calls, guard, lt.InstantModel(today), "fake", 1,
                         deadline=float("inf"))
    assert [r.turn for r in rows] == [1, 2]                       # booked on the "haan"
    assert rows[0].tool_calls == "check_availability+book_visit" and not rows[0].booked
    assert rows[1].booked and rows[1].model_calls == 0
    assert not any(r.error for r in rows)


def test_instant_model_recovers_when_the_slot_is_taken(salon, clock):
    today = clock["now"].date()
    guard = Guard(salon, SqliteBookingStore(),
                  CallStore(fakeredis.FakeRedis(decode_responses=True)), AuditLog(),
                  now=lambda: clock["now"])
    a, b = lt.caller_scripts(salon, 2, today)
    b.start, b.day, b.lines[0] = a.start, a.day, a.lines[0].replace(a.name, b.name).replace(
        a.phone, b.phone)
    model = lt.InstantModel(today)
    lt.run_caller(a, salon, guard.calls, guard, model, "fake", 2, float("inf"))
    rows = lt.run_caller(b, salon, guard.calls, guard, model, "fake", 2, float("inf"))
    assert any(r.booked for r in rows)                            # got another time
    booked = guard.bookings.for_staff("glow-salon", "ravi", a.start, a.start.replace(hour=23))
    assert len(booked) == 2 and len({x.start for x in booked}) == 2


def test_summary_table_renders():
    rows = [lt.TurnRow("fake", 10, c, t, 0.01 * t, 1, "", 100, 90, t == 2, False, False, False)
            for c in range(10) for t in (1, 2)]
    rows.append(lt.TurnRow("fake", 10, 99, 1, 0, 0, "", 0, 0, False, False, False, False,
                           "sqlite3.OperationalError: database is locked"))
    table = lt.summarize(rows, {10: 2.0})
    assert "| 10 | 10/11 |" in table and "| 1 |" in table        # 1 error row
    assert "90%" in table


def test_budget_exceeded_is_recorded(salon, clock):
    today = clock["now"].date()
    guard = Guard(salon, SqliteBookingStore(),
                  CallStore(fakeredis.FakeRedis(decode_responses=True)), AuditLog(),
                  now=lambda: clock["now"])
    script = lt.caller_scripts(salon, 1, today)[0]
    rows = lt.run_caller(script, salon, guard.calls, guard, lt.InstantModel(today), "fake", 1,
                         deadline=0.0)
    assert rows[0].error == "budget exceeded"
