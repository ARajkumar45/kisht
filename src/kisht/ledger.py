"""The lender's loan book: borrowers, loans, EMI schedules, payments, promises-to-pay,
payment links, contact attempts (with case notes) and escalations. SQLite now; same API on
Postgres later (the Store port).

What storage itself guarantees, even with many conversations at once (each write that checks
something runs inside one BEGIN IMMEDIATE transaction, as the M4 booking store did):
  - a loan never has more open promises than the limit passed in;
  - a payment link with the same idempotency key is created once;
  - payments are applied to the oldest unpaid instalment first.
Policy (calling hours, limits from the lender's YAML) lives in the guard, not here.
"""
from __future__ import annotations

import sqlite3
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS borrowers (
  id TEXT PRIMARY KEY, lender_id TEXT NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL,
  language TEXT NOT NULL, dob TEXT NOT NULL, pincode TEXT NOT NULL, city TEXT NOT NULL,
  dnd INTEGER NOT NULL DEFAULT 0, opted_out INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS loans (
  id TEXT PRIMARY KEY, lender_id TEXT NOT NULL, borrower_id TEXT NOT NULL REFERENCES borrowers(id),
  product TEXT NOT NULL, principal INTEGER NOT NULL, emi INTEGER NOT NULL,
  tenure_months INTEGER NOT NULL, first_due TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active');
CREATE TABLE IF NOT EXISTS instalments (
  loan_id TEXT NOT NULL REFERENCES loans(id), seq INTEGER NOT NULL, due_date TEXT NOT NULL,
  amount INTEGER NOT NULL, paid INTEGER NOT NULL DEFAULT 0, paid_on TEXT,
  PRIMARY KEY (loan_id, seq));
CREATE TABLE IF NOT EXISTS promises (
  id TEXT PRIMARY KEY, loan_id TEXT NOT NULL, amount INTEGER NOT NULL, promised_date TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open', call_id TEXT, created_utc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS payment_links (
  id TEXT PRIMARY KEY, loan_id TEXT NOT NULL, amount INTEGER NOT NULL, url TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'created',
  call_id TEXT, created_utc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contacts (
  id TEXT PRIMARY KEY, lender_id TEXT NOT NULL, borrower_id TEXT NOT NULL, loan_id TEXT,
  channel TEXT NOT NULL, started_utc TEXT NOT NULL, outcome TEXT, note TEXT, call_id TEXT);
CREATE TABLE IF NOT EXISTS escalations (
  id TEXT PRIMARY KEY, loan_id TEXT NOT NULL, reason TEXT NOT NULL, summary TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open', call_id TEXT, created_utc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS followups (
  id TEXT PRIMARY KEY, loan_id TEXT NOT NULL, on_date TEXT NOT NULL, reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'planned', call_id TEXT, created_utc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plans (
  plan_date TEXT NOT NULL, loan_id TEXT NOT NULL, channel TEXT NOT NULL, priority TEXT NOT NULL,
  reason TEXT NOT NULL, approach TEXT NOT NULL, status TEXT NOT NULL, created_utc TEXT NOT NULL,
  PRIMARY KEY (plan_date, loan_id));
CREATE INDEX IF NOT EXISTS ix_inst_due ON instalments (due_date);
CREATE INDEX IF NOT EXISTS ix_contacts_b ON contacts (borrower_id, started_utc);
CREATE INDEX IF NOT EXISTS ix_loans_b ON loans (borrower_id);
CREATE INDEX IF NOT EXISTS ix_promises_loan ON promises (loan_id, status);
CREATE INDEX IF NOT EXISTS ix_promises_call ON promises (call_id);
CREATE INDEX IF NOT EXISTS ix_links_call ON payment_links (call_id);
CREATE INDEX IF NOT EXISTS ix_esc_call ON escalations (call_id);
CREATE INDEX IF NOT EXISTS ix_followups_call ON followups (call_id);
"""


class LedgerError(Exception):
    pass


class PromiseLimit(LedgerError):
    """The loan already has the maximum number of open promises."""


@dataclass(frozen=True)
class Dues:
    loan_id: str
    overdue_amount: int          # unpaid amount of instalments already past due
    days_past_due: int           # days since the oldest unpaid instalment fell due (0 if none)
    next_due_date: date | None   # first unpaid instalment due today or later
    next_due_amount: int
    oldest_unpaid_due: date | None

    def as_dict(self) -> dict[str, Any]:
        return {"loan_id": self.loan_id, "overdue_amount": self.overdue_amount,
                "days_past_due": self.days_past_due,
                "next_due_date": self.next_due_date.isoformat() if self.next_due_date else None,
                "next_due_amount": self.next_due_amount}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, 28))       # EMIs fall on day 1-28 in this book


class SqliteLedger:
    """One SQLite connection per thread (shared connections broke under load in M4)."""

    def __init__(self, path: str | Path = ":memory:"):
        if path == ":memory:":
            path = Path(tempfile.mkdtemp(prefix="ledger_")) / "ledger.sqlite"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = Path(path)
        self._uri = f"file:{self.path.resolve()}"
        self._local = threading.local()
        self._keepalive = self._connect()
        self._keepalive.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._uri, uri=True, isolation_level=None, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        # WAL: the dashboard reading does not block the bridge writing (two processes).
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    @property
    def db(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._local.conn = self._connect()
        return conn

    def _write(self, fn):
        db = self.db
        db.execute("BEGIN IMMEDIATE")
        try:
            result = fn(db)
            db.execute("COMMIT")
            return result
        except BaseException:
            db.execute("ROLLBACK")
            raise

    # ---------- setup ----------

    def add_borrower(self, *, lender_id: str, name: str, phone: str, language: str, dob: date,
                     pincode: str, city: str, dnd: bool = False, borrower_id: str | None = None,
                     ) -> str:
        bid = borrower_id or _id("br")
        self.db.execute("INSERT INTO borrowers VALUES (?,?,?,?,?,?,?,?,?,0)",
                        (bid, lender_id, name, phone, language, dob.isoformat(), pincode, city,
                         int(dnd)))
        return bid

    def add_loan(self, *, lender_id: str, borrower_id: str, product: str, principal: int, emi: int,
                 tenure_months: int, first_due: date, loan_id: str | None = None) -> str:
        lid = loan_id or _id("ln")

        def write(db):
            db.execute("INSERT INTO loans VALUES (?,?,?,?,?,?,?,?, 'active')",
                       (lid, lender_id, borrower_id, product, principal, emi, tenure_months,
                        first_due.isoformat()))
            db.executemany("INSERT INTO instalments (loan_id, seq, due_date, amount) "
                           "VALUES (?,?,?,?)",
                           [(lid, i + 1, add_months(first_due, i).isoformat(), emi)
                            for i in range(tenure_months)])
        self._write(write)
        return lid

    # ---------- reads ----------

    def borrower(self, borrower_id: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM borrowers WHERE id=?", (borrower_id,)).fetchone()
        return dict(row) if row else None

    def loan(self, loan_id: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM loans WHERE id=?", (loan_id,)).fetchone()
        return dict(row) if row else None

    def loans_for(self, borrower_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM loans WHERE borrower_id=? ORDER BY id", (borrower_id,))]

    def instalments(self, loan_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM instalments WHERE loan_id=? ORDER BY seq", (loan_id,))]

    def dues(self, loan_id: str, today: date) -> Dues:
        unpaid = [i for i in self.instalments(loan_id) if i["paid"] < i["amount"]]
        past = [i for i in unpaid if date.fromisoformat(i["due_date"]) < today]
        upcoming = [i for i in unpaid if date.fromisoformat(i["due_date"]) >= today]
        oldest = date.fromisoformat(unpaid[0]["due_date"]) if unpaid else None
        return Dues(
            loan_id=loan_id,
            overdue_amount=sum(i["amount"] - i["paid"] for i in past),
            days_past_due=(today - date.fromisoformat(past[0]["due_date"])).days if past else 0,
            next_due_date=date.fromisoformat(upcoming[0]["due_date"]) if upcoming else None,
            next_due_amount=(upcoming[0]["amount"] - upcoming[0]["paid"]) if upcoming else 0,
            oldest_unpaid_due=oldest)

    def due_accounts(self, lender_id: str, today: date, *, days_ahead: int = 3,
                     max_dpd: int = 30) -> list[dict[str, Any]]:
        """Loans with an EMI due within `days_ahead` days, or overdue by at most `max_dpd` days
        (pre-due reminders and early collections only). The planner ranks these."""
        out = []
        for loan in self.db.execute(
                "SELECT l.*, b.name, b.language, b.dnd, b.opted_out FROM loans l "
                "JOIN borrowers b ON b.id = l.borrower_id "
                "WHERE l.lender_id=? AND l.status='active' ORDER BY l.id", (lender_id,)):
            d = self.dues(loan["id"], today)
            pre_due = (d.overdue_amount == 0 and d.next_due_date is not None
                       and (d.next_due_date - today).days <= days_ahead)
            early = 0 < d.days_past_due <= max_dpd
            if pre_due or early:
                out.append({"loan_id": loan["id"], "borrower_id": loan["borrower_id"],
                            "name": loan["name"], "language": loan["language"],
                            "product": loan["product"], "emi": loan["emi"],
                            "dnd": bool(loan["dnd"]), "opted_out": bool(loan["opted_out"]),
                            "open_promise": bool(self.open_promises(loan["id"])),
                            **d.as_dict()})
        return out

    # ---------- writes ----------

    def record_payment(self, loan_id: str, amount: int, paid_on: date) -> int:
        """Apply a payment to the oldest unpaid instalments. Returns the unapplied remainder.
        Open promises on the loan are marked kept once nothing past due remains."""
        if amount <= 0:
            raise LedgerError("payment must be positive")

        def write(db):
            left = amount
            for i in db.execute("SELECT * FROM instalments WHERE loan_id=? AND paid < amount "
                                "ORDER BY seq", (loan_id,)).fetchall():
                if left <= 0:
                    break
                take = min(left, i["amount"] - i["paid"])
                db.execute("UPDATE instalments SET paid = paid + ?, paid_on=? "
                           "WHERE loan_id=? AND seq=?", (take, paid_on.isoformat(), loan_id,
                                                          i["seq"]))
                left -= take
            db.execute("UPDATE promises SET status='kept' WHERE loan_id=? AND status='open' "
                       "AND amount <= ?", (loan_id, amount))
            return left
        return self._write(write)

    def add_promise(self, *, loan_id: str, amount: int, promised_date: date, max_open: int,
                    call_id: str | None = None) -> str:
        pid = _id("pp")

        def write(db):
            n = db.execute("SELECT COUNT(*) FROM promises WHERE loan_id=? AND status='open'",
                           (loan_id,)).fetchone()[0]
            if n >= max_open:
                raise PromiseLimit(f"loan {loan_id} already has {n} open promise(s)")
            db.execute("INSERT INTO promises VALUES (?,?,?,?, 'open', ?, ?)",
                       (pid, loan_id, amount, promised_date.isoformat(), call_id, _now()))
        self._write(write)
        return pid

    def open_promises(self, loan_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM promises WHERE loan_id=? AND status='open' ORDER BY created_utc",
            (loan_id,))]

    def create_payment_link(self, *, loan_id: str, amount: int, idempotency_key: str,
                            call_id: str | None = None) -> dict[str, Any]:
        """Mock UPI link. The same idempotency key always returns the same link."""
        def write(db):
            row = db.execute("SELECT * FROM payment_links WHERE idempotency_key=?",
                             (idempotency_key,)).fetchone()
            if row:
                return dict(row) | {"reused": True}
            lid = _id("pl")
            url = f"https://pay.example.test/upi/{lid}"
            db.execute("INSERT INTO payment_links VALUES (?,?,?,?,?, 'created', ?, ?)",
                       (lid, loan_id, amount, url, idempotency_key, call_id, _now()))
            return {"id": lid, "loan_id": loan_id, "amount": amount, "url": url,
                    "status": "created", "reused": False}
        return self._write(write)

    def log_contact(self, *, lender_id: str, borrower_id: str, channel: str,
                    loan_id: str | None = None, call_id: str | None = None,
                    started_utc: str | None = None) -> str:
        cid = _id("ct")
        self.db.execute("INSERT INTO contacts VALUES (?,?,?,?,?,?,NULL,NULL,?)",
                        (cid, lender_id, borrower_id, loan_id, channel, started_utc or _now(),
                         call_id))
        return cid

    def add_desk_note(self, *, lender_id: str, borrower_id: str, loan_id: str, note: str) -> str:
        """What the human desk agreed with the borrower. Stored with the case notes, so the
        agent reads it (after identity) the next time it talks to this borrower."""
        cid = self.log_contact(lender_id=lender_id, borrower_id=borrower_id, loan_id=loan_id,
                               channel="desk")
        self.close_contact(cid, "desk_resolved", note[:500])
        return cid

    def close_contact(self, contact_id: str, outcome: str, note: str) -> None:
        self.db.execute("UPDATE contacts SET outcome=?, note=? WHERE id=?",
                        (outcome, note, contact_id))

    def contacts_since(self, borrower_id: str, since_utc: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM contacts WHERE borrower_id=? AND started_utc >= ? "
            "ORDER BY started_utc", (borrower_id, since_utc))]

    def recent_notes(self, borrower_id: str, limit: int = 3) -> list[dict[str, Any]]:
        """Memory: the last case notes, newest first."""
        return [dict(r) for r in self.db.execute(
            "SELECT started_utc, channel, outcome, note FROM contacts "
            "WHERE borrower_id=? AND note IS NOT NULL ORDER BY started_utc DESC LIMIT ?",
            (borrower_id, limit))]

    def set_opted_out(self, borrower_id: str) -> None:
        self.db.execute("UPDATE borrowers SET opted_out=1 WHERE id=?", (borrower_id,))

    def add_escalation(self, *, loan_id: str, reason: str, summary: str,
                       call_id: str | None = None) -> str:
        eid = _id("es")
        self.db.execute("INSERT INTO escalations VALUES (?,?,?,?, 'open', ?, ?)",
                        (eid, loan_id, reason, summary, call_id, _now()))
        return eid

    def add_followup(self, *, loan_id: str, on_date: date, reason: str,
                     call_id: str | None = None) -> str:
        fid = _id("fu")
        self.db.execute("INSERT INTO followups VALUES (?,?,?,?, 'planned', ?, ?)",
                        (fid, loan_id, on_date.isoformat(), reason, call_id, _now()))
        return fid

    def followups(self, loan_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM followups WHERE loan_id=? ORDER BY on_date", (loan_id,))]

    def save_plan_item(self, *, plan_date: date, loan_id: str, channel: str, priority: str,
                       reason: str, approach: str, status: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO plans VALUES (?,?,?,?,?,?,?,?)",
                        (plan_date.isoformat(), loan_id, channel, priority, reason[:200],
                         approach[:200], status, _now()))

    def plan_for(self, loan_id: str, plan_date: date) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM plans WHERE loan_id=? AND plan_date=?",
                              (loan_id, plan_date.isoformat())).fetchone()
        return dict(row) if row else None

    def missed_promises(self, loan_id: str, today: date) -> list[dict[str, Any]]:
        """Open promises whose date has passed (the borrower did not pay as promised)."""
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM promises WHERE loan_id=? AND status='open' AND promised_date < ?",
            (loan_id, today.isoformat()))]

    def open_escalations_for_borrower(self, borrower_id: str) -> list[dict[str, Any]]:
        """Cases the human desk has not resolved yet, on any loan of this borrower."""
        return [dict(r) for r in self.db.execute(
            "SELECT e.* FROM escalations e JOIN loans l ON l.id = e.loan_id "
            "WHERE l.borrower_id=? AND e.status != 'resolved' ORDER BY e.created_utc",
            (borrower_id,))]

    def escalations(self, loan_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM escalations WHERE loan_id=? ORDER BY created_utc", (loan_id,))]

    def payment_links(self, loan_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM payment_links WHERE loan_id=? ORDER BY created_utc", (loan_id,))]
