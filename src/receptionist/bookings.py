"""Booking storage behind a small interface (SQLite now, Postgres in M7).

The one rule storage itself must guarantee: a staff member is never booked twice
at overlapping times, even if two calls try at the same moment. SQLite does the
overlap check and the insert inside one write transaction.
"""
from __future__ import annotations

import sqlite3
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol


class SlotTaken(Exception):
    """The staff member already has a booking that overlaps this time."""


@dataclass(frozen=True)
class Booking:
    id: str
    business_id: str
    staff_id: str
    service_id: str
    start: datetime          # timezone-aware
    end: datetime            # timezone-aware
    customer_name: str
    customer_phone: str
    call_id: str | None = None
    status: str = "confirmed"


class BookingStore(Protocol):
    def add(self, booking: Booking) -> Booking: ...
    def for_staff(self, business_id: str, staff_id: str,
                  start: datetime, end: datetime) -> list[Booking]: ...
    def get(self, booking_id: str) -> Booking | None: ...


def _utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("booking times must be timezone-aware")
    return dt.astimezone(UTC).isoformat()


def new_booking_id() -> str:
    return "bk_" + uuid.uuid4().hex[:10]


class SqliteBookingStore:
    """One SQLite connection per thread (sqlite3 connections must not be shared across
    threads: the M4 load test broke 9 of 10 concurrent callers with a shared one).
    `:memory:` (tests) becomes a throw-away temp file, because an in-memory database
    is private to one connection and SQLite's shared-cache mode locks whole tables."""

    def __init__(self, path: str | Path = ":memory:"):
        if path == ":memory:":
            path = Path(tempfile.mkdtemp(prefix="bookings_")) / "bookings.sqlite"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._uri = f"file:{Path(path).resolve()}"
        self._local = threading.local()
        self._keepalive = self._connect()
        self._keepalive.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL,
                staff_id TEXT NOT NULL,
                service_id TEXT NOT NULL,
                start_utc TEXT NOT NULL,
                end_utc TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                customer_phone TEXT NOT NULL,
                call_id TEXT,
                status TEXT NOT NULL,
                created_utc TEXT NOT NULL
            )""")
        self._keepalive.execute("CREATE INDEX IF NOT EXISTS ix_staff_time "
                                "ON bookings (business_id, staff_id, start_utc)")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._uri, uri=True, isolation_level=None, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    @property
    def db(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._local.conn = self._connect()
        return conn

    def add(self, booking: Booking) -> Booking:
        start, end = _utc(booking.start), _utc(booking.end)
        if start >= end:
            raise ValueError("booking must end after it starts")
        db = self.db
        db.execute("BEGIN IMMEDIATE")   # take the write lock before checking
        try:
            clash = db.execute(
                "SELECT id FROM bookings WHERE business_id=? AND staff_id=? "
                "AND status='confirmed' AND start_utc < ? AND end_utc > ?",
                (booking.business_id, booking.staff_id, end, start)).fetchone()
            if clash:
                raise SlotTaken(f"{booking.staff_id} is already booked at that time")
            db.execute(
                "INSERT INTO bookings VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (booking.id, booking.business_id, booking.staff_id, booking.service_id,
                 start, end, booking.customer_name, booking.customer_phone,
                 booking.call_id, booking.status, datetime.now(UTC).isoformat()))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        return booking

    def for_staff(self, business_id: str, staff_id: str,
                  start: datetime, end: datetime) -> list[Booking]:
        rows = self.db.execute(
            "SELECT * FROM bookings WHERE business_id=? AND staff_id=? "
            "AND status='confirmed' AND start_utc < ? AND end_utc > ? ORDER BY start_utc",
            (business_id, staff_id, _utc(end), _utc(start))).fetchall()
        return [self._row(r, start.tzinfo) for r in rows]

    def get(self, booking_id: str) -> Booking | None:
        row = self.db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        return self._row(row, UTC) if row else None

    @staticmethod
    def _row(r: sqlite3.Row, tz) -> Booking:
        return Booking(
            id=r["id"], business_id=r["business_id"], staff_id=r["staff_id"],
            service_id=r["service_id"],
            start=datetime.fromisoformat(r["start_utc"]).astimezone(tz),
            end=datetime.fromisoformat(r["end_utc"]).astimezone(tz),
            customer_name=r["customer_name"], customer_phone=r["customer_phone"],
            call_id=r["call_id"], status=r["status"])
