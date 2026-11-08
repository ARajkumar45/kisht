"""Shared test setup. The clock is fixed: Monday 2026-11-09, 09:00 in Bengaluru."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import fakeredis
import pytest

from receptionist.audit import AuditLog
from receptionist.bookings import SqliteBookingStore
from receptionist.business import load_business
from receptionist.guard import Guard
from receptionist.notebook import CallStore

IST = ZoneInfo("Asia/Kolkata")
SALON = Path(__file__).resolve().parent.parent / "businesses" / "glow-salon.yaml"


@pytest.fixture
def clock():
    return {"now": datetime(2026, 11, 9, 9, 0, tzinfo=IST)}


@pytest.fixture
def salon():
    return load_business(SALON)


@pytest.fixture
def guard(clock, salon):
    return Guard(business=salon, bookings=SqliteBookingStore(),
                 calls=CallStore(fakeredis.FakeRedis(decode_responses=True)),
                 audit=AuditLog(), now=lambda: clock["now"])
