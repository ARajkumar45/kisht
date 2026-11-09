"""The guard: business rules enforced in code, never only in the prompt (D42–D46).

The model can only *ask*. Booking is two steps:
  1. propose_booking  -> checks every rule, saves a pending booking in the call
                         state, returns the read-back sentence (D44).
  2. confirm_booking  -> books only if the caller's own reply was marked as a
                         clear yes for that exact pending booking (D43).
Who marks the yes? Session code, from the caller's words (confirm.py, step 5) —
never the model. Every decision, allowed or refused, goes to the audit log (D46).
"""
from __future__ import annotations

import functools
import re
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from receptionist.audit import AuditLog
from receptionist.bookings import Booking, BookingStore, SlotTaken, new_booking_id
from receptionist.business import WEEKDAYS, Business
from receptionist.notebook import CallStore

MAX_SLOTS_RETURNED = 6


class GuardRefused(Exception):
    """A request breaks a rule. `code` is stable for tests; `message` is for the model."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _audited(action: str):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(self: Guard, call_id: str, **kwargs):
            try:
                result = fn(self, call_id, **kwargs)
            except GuardRefused as e:
                self.audit.record(call_id=call_id, business_id=self.business.business_id,
                                  action=action, args=kwargs, outcome="denied",
                                  detail=f"{e.code}: {e.message}")
                raise
            self.audit.record(call_id=call_id, business_id=self.business.business_id,
                              action=action, args=kwargs, outcome="ok",
                              detail=_summary(result))
            return result
        return wrapper
    return decorator


def _summary(result: Any) -> str:
    if isinstance(result, dict) and "id" in result:
        return f"id={result['id']}"
    if isinstance(result, dict) and "total_free" in result:
        return f"{len(result['slots'])} of {result['total_free']} free slot(s)"
    return ""


class Guard:
    def __init__(self, business: Business, bookings: BookingStore, calls: CallStore,
                 audit: AuditLog, now: Callable[[], datetime] | None = None):
        self.business = business
        self.bookings = bookings
        self.calls = calls
        self.audit = audit
        self.tz = ZoneInfo(business.timezone)
        self._now = now or (lambda: datetime.now(self.tz))

    def now(self) -> datetime:
        return self._now().astimezone(self.tz)

    # ---------- reading ----------

    @_audited("check_availability")
    def check_availability(self, call_id: str, *, service_id: str, day: str,
                           preferred_time: str | None = None,
                           staff_id: str | None = None) -> dict[str, Any]:
        """Up to MAX_SLOTS_RETURNED free starts: the closest to preferred_time if given,
        otherwise spread across the day. total_free says how many there are in all."""
        service = self._service(service_id)
        on = self._parse_day(day)
        self._check_day_in_range(on)
        staff = self._staff_for(service_id, staff_id)
        slots: dict[datetime, dict[str, str]] = {}
        for person in staff:
            for start in self._free_starts(person.id, service.duration_min, on):
                slots.setdefault(start, {"start": start.strftime("%Y-%m-%dT%H:%M"),
                                         "staff_id": person.id, "staff_name": person.name})
        starts = sorted(slots)
        if preferred_time:
            target = datetime.combine(on, self._parse_clock(preferred_time), self.tz)
            keep = sorted(sorted(starts, key=lambda t: abs(t - target))[:MAX_SLOTS_RETURNED])
        elif len(starts) <= MAX_SLOTS_RETURNED:
            keep = starts
        else:
            last = len(starts) - 1
            keep = [starts[round(i * last / (MAX_SLOTS_RETURNED - 1))]
                    for i in range(MAX_SLOTS_RETURNED)]
        return {"slots": [slots[t] for t in keep], "total_free": len(starts)}

    # ---------- booking, step 1 ----------

    @_audited("propose_booking")
    def propose_booking(self, call_id: str, *, service_id: str, start: str,
                        customer_name: str, customer_phone: str,
                        staff_id: str | None = None) -> dict[str, Any]:
        service = self._service(service_id)
        begin = self._parse_start(start)
        name = customer_name.strip()
        if not name:
            raise GuardRefused("missing_name", "Ask the caller for their name first.")
        phone = re.sub(r"\D", "", customer_phone)
        if len(phone) < 10:
            raise GuardRefused("bad_phone", "Ask the caller for a 10-digit phone number.")
        person = self._pick_free_staff(service_id, staff_id, begin, service.duration_min)
        # The read-back is spoken to the caller, so it follows the call's language (D84:
        # a Hindi caller heard an English "Shall I book it?" in the M5 voice probe).
        language = self.calls.get(call_id, "language", self.business.languages.default)
        if language == "hi":
            summary = (f"{service.name}, {person.name} ke saath, {begin:%A %d %B} ko "
                       f"{begin:%I:%M %p} baje, {name} ke liye, phone ending {phone[-4:]}")
            question = ". Book kar doon?"
        else:
            summary = (f"{service.name} with {person.name} on {begin:%A %d %B} at "
                       f"{begin:%I:%M %p}, for {name}, phone ending {phone[-4:]}")
            question = ". Shall I book it?"
        pending = {
            "id": "pb_" + uuid.uuid4().hex[:8],
            "service_id": service.id,
            "staff_id": person.id,
            "start": begin.isoformat(),
            "customer_name": name,
            "customer_phone": phone,
            "summary": summary,
            "read_back": summary + question,
        }
        self.calls.set_state(call_id, pending_booking=pending)
        self.calls.clear(call_id, "caller_confirmed")   # a new proposal needs a new yes
        return pending

    # ---------- booking, step 2 ----------

    @_audited("confirm_booking")
    def confirm_booking(self, call_id: str, *, pending_id: str) -> dict[str, Any]:
        pending = self.calls.get(call_id, "pending_booking")
        if not pending or pending["id"] != pending_id:
            raise GuardRefused("no_pending", "There is no booking waiting for confirmation. "
                                             "Propose the booking and read it back first.")
        if self.calls.get(call_id, "caller_confirmed") != pending_id:
            raise GuardRefused("no_yes", "The caller has not said yes to this booking. "
                                         "Read it back and ask them to confirm.")
        service = self._service(pending["service_id"])
        begin = datetime.fromisoformat(pending["start"])
        self._check_start_rules(begin, service.duration_min)  # time may have moved on
        booking = Booking(
            id=new_booking_id(), business_id=self.business.business_id,
            staff_id=pending["staff_id"], service_id=service.id,
            start=begin, end=begin + timedelta(minutes=service.duration_min),
            customer_name=pending["customer_name"],
            customer_phone=pending["customer_phone"], call_id=call_id)
        try:
            self.bookings.add(booking)
        except SlotTaken:
            raise GuardRefused("slot_taken", "That time was just taken. "
                                             "Offer the caller other times.") from None
        finally:
            self.calls.clear(call_id, "pending_booking", "caller_confirmed")
        return {"id": booking.id, "start": begin.isoformat(), "staff_id": booking.staff_id,
                "service_id": service.id}

    def mark_caller_yes(self, call_id: str) -> str | None:
        """Called by session code when the caller's own words are a clear yes.

        Marks the *current* pending booking as confirmed and returns its id
        (or None if nothing is pending). Not exposed to the model as a tool.
        """
        pending = self.calls.get(call_id, "pending_booking")
        if not pending:
            return None
        self.calls.set_state(call_id, caller_confirmed=pending["id"])
        self.audit.record(call_id=call_id, business_id=self.business.business_id,
                          action="caller_yes", args={"pending_id": pending["id"]}, outcome="ok")
        return pending["id"]

    # ---------- rules ----------

    def _service(self, service_id: str):
        try:
            return self.business.service(service_id)
        except KeyError:
            names = ", ".join(f"{s.id} ({s.name})" for s in self.business.services)
            raise GuardRefused("unknown_service",
                               f"No service {service_id!r}. Services: {names}.") from None

    def _staff_for(self, service_id: str, staff_id: str | None):
        staff = self.business.staff_for(service_id)
        if staff_id is None:
            return staff
        chosen = [p for p in staff if p.id == staff_id]
        if not chosen:
            raise GuardRefused("wrong_staff", f"{staff_id!r} does not do {service_id!r}. "
                               f"Who does: {', '.join(p.name for p in staff)}.")
        return chosen

    def _parse_day(self, day: str) -> date:
        try:
            return date.fromisoformat(day)
        except ValueError:
            raise GuardRefused("bad_date", "Use a date like 2026-11-09.") from None

    def _parse_clock(self, clock: str):
        try:
            return datetime.strptime(clock.strip(), "%H:%M").time()
        except ValueError:
            raise GuardRefused("bad_time", "Use a time like 11:00 (24-hour).") from None

    def _parse_start(self, start: str) -> datetime:
        try:
            dt = datetime.fromisoformat(start)
        except ValueError:
            raise GuardRefused("bad_time", "Use a start like 2026-11-09T11:00.") from None
        return dt.replace(tzinfo=self.tz) if dt.tzinfo is None else dt.astimezone(self.tz)

    def _check_day_in_range(self, on: date) -> None:
        today = self.now().date()
        if on < today:
            raise GuardRefused("in_past", "That date has already passed.")
        if on > today + timedelta(days=self.business.rules.max_days_ahead):
            raise GuardRefused("too_far", f"Bookings open only "
                               f"{self.business.rules.max_days_ahead} days ahead.")

    def _windows(self, on: date) -> list[tuple[datetime, datetime]]:
        day_key = WEEKDAYS[on.weekday()]
        return [(datetime.combine(on, a, self.tz), datetime.combine(on, b, self.tz))
                for a, b in self.business.hours.get(day_key, [])]

    def _check_start_rules(self, begin: datetime, duration_min: int) -> None:
        rules = self.business.rules
        self._check_day_in_range(begin.date())
        if begin < self.now() + timedelta(minutes=rules.min_notice_min):
            raise GuardRefused("too_soon", f"Bookings need at least "
                               f"{rules.min_notice_min} minutes' notice.")
        if (begin.hour * 60 + begin.minute) % rules.slot_step_min or begin.second:
            raise GuardRefused("off_grid", f"Start times are every {rules.slot_step_min} "
                                           f"minutes.")
        end = begin + timedelta(minutes=duration_min)
        if not any(a <= begin and end <= b for a, b in self._windows(begin.date())):
            raise GuardRefused("closed", "The business is closed at that time, or the "
                                         "service would run past closing.")

    def _is_free(self, staff_id: str, begin: datetime, end: datetime) -> bool:
        return not self.bookings.for_staff(self.business.business_id, staff_id, begin, end)

    def _free_starts(self, staff_id: str, duration_min: int, on: date):
        step = timedelta(minutes=self.business.rules.slot_step_min)
        length = timedelta(minutes=duration_min)
        for a, b in self._windows(on):
            t = a
            while t + length <= b:
                try:
                    self._check_start_rules(t, duration_min)
                except GuardRefused:
                    t += step
                    continue
                if self._is_free(staff_id, t, t + length):
                    yield t
                t += step

    def _pick_free_staff(self, service_id: str, staff_id: str | None,
                         begin: datetime, duration_min: int):
        self._check_start_rules(begin, duration_min)
        end = begin + timedelta(minutes=duration_min)
        for person in self._staff_for(service_id, staff_id):
            if self._is_free(person.id, begin, end):
                return person
        raise GuardRefused("slot_taken", "That time is not free. Offer the caller other times.")
