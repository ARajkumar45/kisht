"""Guard rules. The clock is fixed: Monday 2026-11-09, 09:00 in Bengaluru.

Glow Salon hours: Mon–Fri 10:00–20:00, Sat 09:00–21:00, Sun 10:00–14:00.
Rules: 15-minute grid, 60 minutes' notice, 14 days ahead.
"""
from datetime import datetime, timedelta

import fakeredis
import pytest
from conftest import IST, SALON

from receptionist.audit import AuditLog
from receptionist.bookings import Booking, SlotTaken, SqliteBookingStore
from receptionist.business import load_business
from receptionist.guard import Guard, GuardRefused
from receptionist.notebook import CallStore

PHONE = "+91 98450 12345"


def new_call(guard):
    return guard.calls.start_call("glow-salon", "en")


def book(guard, call_id, start, service_id="haircut-men", staff_id=None):
    """Full happy path: propose -> caller says yes -> confirm."""
    pending = guard.propose_booking(call_id, service_id=service_id, start=start,
                                    customer_name="Priya", customer_phone=PHONE,
                                    staff_id=staff_id)
    guard.mark_caller_yes(call_id)
    return guard.confirm_booking(call_id, pending_id=pending["id"])


# ---------- availability ----------

def test_availability_spreads_six_slots_over_the_day(guard):
    found = guard.check_availability(new_call(guard), service_id="haircut-men", day="2026-11-10")
    slots = found["slots"]
    assert found["total_free"] == 39                    # 10:00 .. 19:30 every 15 min
    assert len(slots) == 6
    assert slots[0] == {"start": "2026-11-10T10:00", "staff_id": "ravi", "staff_name": "Ravi"}
    assert slots[-1]["start"] == "2026-11-10T19:30"     # last start that ends by 20:00


def test_preferred_time_returns_the_closest_slots(guard):
    found = guard.check_availability(new_call(guard), service_id="haircut-men",
                                     day="2026-11-10", preferred_time="12:00")
    starts = [s["start"][-5:] for s in found["slots"]]
    assert "12:00" in starts and len(starts) == 6
    assert starts == sorted(starts) and starts[0] >= "11:15" and starts[-1] <= "12:45"
    with pytest.raises(GuardRefused) as e:
        guard.check_availability(new_call(guard), service_id="haircut-men",
                                 day="2026-11-10", preferred_time="noon")
    assert e.value.code == "bad_time"


def test_availability_skips_booked_times(guard):
    call = new_call(guard)
    book(guard, call, "2026-11-10T10:00")
    starts = [s["start"][-5:] for s in guard.check_availability(
        new_call(guard), service_id="haircut-men", day="2026-11-10")["slots"]]
    assert "10:00" not in starts and "10:15" not in starts   # 30-min haircut until 10:30
    assert starts[0] == "10:30"


def test_availability_today_respects_notice(guard, clock):
    clock["now"] = datetime(2026, 11, 9, 10, 20, tzinfo=IST)
    slots = guard.check_availability(new_call(guard), service_id="haircut-men",
                                     day="2026-11-09")["slots"]
    assert slots[0]["start"] == "2026-11-09T11:30"   # 10:20 + 60 min, next 15-min mark


def test_long_service_must_finish_before_closing(guard):
    # Sunday closes at 14:00; a 90-minute colour must start by 12:30.
    slots = guard.check_availability(new_call(guard), service_id="hair-colour",
                                     day="2026-11-15")["slots"]
    assert slots and all(s["start"][-5:] <= "12:30" for s in slots)


# ---------- the yes-gate (D43, D44) ----------

def test_proposal_saves_pending_and_reads_back(guard):
    call = new_call(guard)
    p = guard.propose_booking(call, service_id="haircut-men", start="2026-11-10T11:00",
                              customer_name="Priya", customer_phone=PHONE)
    assert "Men's haircut with Ravi on Tuesday 10 November at 11:00 AM" in p["read_back"]
    assert "2345" in p["read_back"]
    assert guard.calls.get(call, "pending_booking")["id"] == p["id"]


def test_read_back_follows_the_callers_language(guard):
    call = new_call(guard)
    guard.calls.set_state(call, language="hi")
    p = guard.propose_booking(call, service_id="haircut-men", start="2026-11-10T11:00",
                              customer_name="Priya", customer_phone=PHONE)
    assert p["read_back"].endswith("Book kar doon?")
    assert "Ravi ke saath" in p["read_back"] and "2345" in p["read_back"]


def test_cannot_book_without_callers_yes(guard):
    call = new_call(guard)
    p = guard.propose_booking(call, service_id="haircut-men", start="2026-11-10T11:00",
                              customer_name="Priya", customer_phone=PHONE)
    with pytest.raises(GuardRefused) as e:
        guard.confirm_booking(call, pending_id=p["id"])
    assert e.value.code == "no_yes"
    found = guard.check_availability(call, service_id="haircut-men", day="2026-11-10",
                                     preferred_time="11:00")
    assert found["slots"][0]["start"].endswith("11:00") or any(
        s["start"].endswith("11:00") for s in found["slots"])   # still free
    assert guard.audit.entries[-2]["outcome"] == "denied"


def test_cannot_confirm_without_a_proposal(guard):
    call = new_call(guard)
    with pytest.raises(GuardRefused) as e:
        guard.confirm_booking(call, pending_id="pb_madeup")
    assert e.value.code == "no_pending"


def test_yes_only_counts_for_the_current_proposal(guard):
    call = new_call(guard)
    first = guard.propose_booking(call, service_id="haircut-men", start="2026-11-10T11:00",
                                  customer_name="Priya", customer_phone=PHONE)
    guard.mark_caller_yes(call)
    second = guard.propose_booking(call, service_id="haircut-men", start="2026-11-10T12:00",
                                   customer_name="Priya", customer_phone=PHONE)
    with pytest.raises(GuardRefused) as e:              # old yes does not carry over
        guard.confirm_booking(call, pending_id=second["id"])
    assert e.value.code == "no_yes"
    with pytest.raises(GuardRefused):                   # old proposal is gone
        guard.confirm_booking(call, pending_id=first["id"])


def test_yes_then_confirm_books_and_clears_pending(guard):
    call = new_call(guard)
    result = book(guard, call, "2026-11-10T11:00")
    saved = guard.bookings.get(result["id"])
    assert saved.staff_id == "ravi" and saved.customer_name == "Priya"
    assert guard.calls.get(call, "pending_booking") is None
    assert guard.calls.get(call, "caller_confirmed") is None
    assert [e["action"] for e in guard.audit.for_call(call)] == [
        "propose_booking", "caller_yes", "confirm_booking"]


# ---------- no double booking ----------

def test_same_staff_cannot_be_double_booked(guard):
    book(guard, new_call(guard), "2026-11-10T11:00")
    with pytest.raises(GuardRefused) as e:
        guard.propose_booking(new_call(guard), service_id="haircut-men",
                              start="2026-11-10T11:15", customer_name="Arun",
                              customer_phone="9845000000")
    assert e.value.code == "slot_taken"


def test_second_caller_gets_the_other_free_stylist(guard):
    book(guard, new_call(guard), "2026-11-10T11:00", service_id="haircut-women")
    p = guard.propose_booking(new_call(guard), service_id="haircut-women",
                              start="2026-11-10T11:00", customer_name="Arun",
                              customer_phone="9845000000")
    assert p["staff_id"] == "meena"


def test_two_calls_racing_for_one_slot_only_one_wins(guard):
    a, b = new_call(guard), new_call(guard)
    pa = guard.propose_booking(a, service_id="haircut-men", start="2026-11-10T11:00",
                               customer_name="Priya", customer_phone=PHONE)
    pb = guard.propose_booking(b, service_id="haircut-men", start="2026-11-10T11:00",
                               customer_name="Arun", customer_phone="9845000000")
    guard.mark_caller_yes(a)
    guard.mark_caller_yes(b)
    guard.confirm_booking(a, pending_id=pa["id"])
    with pytest.raises(GuardRefused) as e:
        guard.confirm_booking(b, pending_id=pb["id"])
    assert e.value.code == "slot_taken"


# ---------- time rules ----------

@pytest.mark.parametrize("start, code", [
    ("2026-11-09T09:30", "too_soon"),       # opens 10:00, but also within 60 min
    ("2026-11-08T11:00", "in_past"),
    ("2026-11-24T11:00", "too_far"),        # 15 days ahead
    ("2026-11-10T11:10", "off_grid"),
    ("2026-11-15T15:00", "closed"),         # Sunday afternoon
    ("2026-11-10T19:00", "closed"),         # 90-min colour would end 20:30
    ("tomorrow 11am", "bad_time"),
])
def test_time_rules(guard, start, code):
    service = "hair-colour" if start == "2026-11-10T19:00" else "haircut-men"
    with pytest.raises(GuardRefused) as e:
        guard.propose_booking(new_call(guard), service_id=service, start=start,
                              customer_name="Priya", customer_phone=PHONE)
    assert e.value.code == code


def test_rules_are_checked_again_at_confirm_time(guard, clock):
    call = new_call(guard)
    p = guard.propose_booking(call, service_id="haircut-men", start="2026-11-09T11:00",
                              customer_name="Priya", customer_phone=PHONE)
    guard.mark_caller_yes(call)
    clock["now"] += timedelta(hours=1, minutes=30)   # caller took ages; now 10:30
    with pytest.raises(GuardRefused) as e:
        guard.confirm_booking(call, pending_id=p["id"])
    assert e.value.code == "too_soon"


# ---------- inputs ----------

@pytest.mark.parametrize("kwargs, code", [
    ({"service_id": "massage"}, "unknown_service"),
    ({"staff_id": "meena"}, "wrong_staff"),            # Meena doesn't do men's haircuts
    ({"customer_name": "  "}, "missing_name"),
    ({"customer_phone": "12345"}, "bad_phone"),
])
def test_bad_inputs_are_refused(guard, kwargs, code):
    args = {"service_id": "haircut-men", "start": "2026-11-10T11:00",
            "customer_name": "Priya", "customer_phone": PHONE} | kwargs
    with pytest.raises(GuardRefused) as e:
        guard.propose_booking(new_call(guard), **args)
    assert e.value.code == code


# ---------- audit ----------

def test_audit_masks_phone_numbers(guard):
    call = new_call(guard)
    guard.propose_booking(call, service_id="haircut-men", start="2026-11-10T11:00",
                          customer_name="Priya", customer_phone=PHONE)
    entry = guard.audit.for_call(call)[0]
    assert entry["args"]["customer_phone"] == "******2345"
    assert "98450" not in str(guard.audit.entries)


def test_audit_file_is_written(tmp_path, clock):
    path = tmp_path / "audit.jsonl"
    g = Guard(business=load_business(SALON), bookings=SqliteBookingStore(),
              calls=CallStore(fakeredis.FakeRedis(decode_responses=True)),
              audit=AuditLog(path), now=lambda: clock["now"])
    g.check_availability(g.calls.start_call("glow-salon", "en"),
                         service_id="haircut-men", day="2026-11-10")
    assert '"action": "check_availability"' in path.read_text()


# ---------- storage on its own ----------

def test_store_blocks_overlap_but_allows_back_to_back():
    store = SqliteBookingStore()
    t = datetime(2026, 11, 10, 11, 0, tzinfo=IST)

    def make(start, minutes, bid):
        return Booking(id=bid, business_id="glow-salon", staff_id="ravi",
                       service_id="haircut-men", start=start,
                       end=start + timedelta(minutes=minutes),
                       customer_name="X", customer_phone="9845000000")
    store.add(make(t, 30, "a"))
    store.add(make(t + timedelta(minutes=30), 30, "b"))          # starts as a ends: fine
    with pytest.raises(SlotTaken):
        store.add(make(t + timedelta(minutes=15), 30, "c"))      # overlaps both


def test_thirty_two_threads_racing_for_one_slot_leave_exactly_one_booking():
    """SQLite store under real concurrency: one connection per thread, write lock wins."""
    import threading
    store = SqliteBookingStore()
    t = datetime(2026, 11, 10, 11, 0, tzinfo=IST)
    outcomes = []
    lock = threading.Lock()

    def attempt(i):
        b = Booking(id=f"race{i}", business_id="glow-salon", staff_id="ravi",
                    service_id="haircut-men", start=t, end=t + timedelta(minutes=30),
                    customer_name=f"C{i}", customer_phone="9845000000")
        try:
            store.add(b)
            result = "ok"
        except SlotTaken:
            result = "taken"
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(32)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert outcomes.count("ok") == 1 and outcomes.count("taken") == 31
    assert len(store.for_staff("glow-salon", "ravi", t, t + timedelta(hours=1))) == 1
