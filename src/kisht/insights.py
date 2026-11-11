"""Contact-centre data: the call log, every turn, trace spans, post-call reviews, and the human
desk. Kept apart from the ledger: the ledger is the lender's loan book (money, promises), this
is what the contact centre needs to see, score and debug its conversations.

SQLite with one connection per thread, like the ledger. Everything is written as it happens,
so a live call is visible turn by turn and nothing expires.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
  call_id TEXT PRIMARY KEY, lender_id TEXT NOT NULL, borrower_id TEXT, loan_id TEXT,
  borrower_name TEXT, channel TEXT NOT NULL, language TEXT, started_utc TEXT NOT NULL,
  ended_utc TEXT, status TEXT NOT NULL DEFAULT 'live', outcome TEXT, note TEXT,
  turns INTEGER NOT NULL DEFAULT 0, blocks INTEGER NOT NULL DEFAULT 0, source TEXT);
CREATE INDEX IF NOT EXISTS calls_started ON calls(started_utc);
CREATE TABLE IF NOT EXISTS turns (
  call_id TEXT NOT NULL, idx INTEGER NOT NULL, at_utc TEXT NOT NULL, language TEXT,
  borrower TEXT NOT NULL, agent TEXT NOT NULL, tools TEXT NOT NULL, refused TEXT NOT NULL,
  replaced TEXT NOT NULL, seconds REAL, model_calls INTEGER, prompt_tokens INTEGER,
  cached_tokens INTEGER, PRIMARY KEY (call_id, idx));
CREATE TABLE IF NOT EXISTS spans (
  span_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, parent_id TEXT, call_id TEXT,
  name TEXT NOT NULL, start_ns INTEGER NOT NULL, end_ns INTEGER NOT NULL, status TEXT,
  attrs TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS spans_call ON spans(call_id);
CREATE TABLE IF NOT EXISTS reviews (
  call_id TEXT PRIMARY KEY, reason TEXT, sentiment TEXT, summary TEXT, qa TEXT NOT NULL,
  qa_score REAL, compliance TEXT NOT NULL, model TEXT, seconds REAL, created_utc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS desk (
  escalation_id TEXT PRIMARY KEY, team TEXT NOT NULL, status TEXT NOT NULL,
  assignee TEXT, resolution TEXT, updated_utc TEXT NOT NULL);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row(r: sqlite3.Row | None, json_cols: tuple[str, ...] = ()) -> dict[str, Any] | None:
    if r is None:
        return None
    d = dict(r)
    for c in json_cols:
        if d.get(c) is not None:
            d[c] = json.loads(d[c])
    return d


class InsightsStore:
    def __init__(self, path: str | Path = ":memory:"):
        if path == ":memory:":
            path = Path(tempfile.mkdtemp(prefix="insights_")) / "insights.sqlite"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = Path(path)
        self._uri = f"file:{self.path.resolve()}"
        self._local = threading.local()
        self._keepalive = self._connect()
        self._keepalive.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._uri, uri=True, isolation_level=None, timeout=30,
                               check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @property
    def db(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._local.conn = self._connect()
        return conn

    # ---------- call log ----------

    def open_call(self, *, call_id: str, lender_id: str, borrower_id: str | None,
                  loan_id: str | None, borrower_name: str | None, channel: str, language: str,
                  greeting: str, source: str = "live") -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO calls (call_id, lender_id, borrower_id, loan_id, "
            "borrower_name, channel, language, started_utc, status, source) "
            "VALUES (?,?,?,?,?,?,?,?, 'live', ?)",
            (call_id, lender_id, borrower_id, loan_id, borrower_name, channel, language, _now(),
             source))
        self.add_turn(call_id, borrower="", agent=greeting, language=language)

    def add_turn(self, call_id: str, *, borrower: str, agent: str, language: str | None = None,
                 tools: list[str] | None = None, refused: list[str] | None = None,
                 replaced: list[str] | None = None, seconds: float | None = None,
                 model_calls: int = 0, prompt_tokens: int = 0, cached_tokens: int = 0) -> None:
        db = self.db
        db.execute("BEGIN IMMEDIATE")
        try:
            idx = db.execute("SELECT COUNT(*) FROM turns WHERE call_id=?",
                             (call_id,)).fetchone()[0]
            db.execute("INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (call_id, idx, _now(), language, borrower, agent,
                        json.dumps(tools or []), json.dumps(refused or []),
                        json.dumps(replaced or []), seconds, model_calls, prompt_tokens,
                        cached_tokens))
            blocks = len(refused or []) + len(replaced or [])
            db.execute("UPDATE calls SET turns = turns + ?, blocks = blocks + ?, "
                       "language = COALESCE(?, language) WHERE call_id=?",
                       (1 if borrower else 0, blocks, language, call_id))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise

    def close_call(self, call_id: str, *, outcome: str, note: str) -> None:
        self.db.execute("UPDATE calls SET status='ended', ended_utc=?, outcome=?, note=? "
                        "WHERE call_id=?", (_now(), outcome, note, call_id))

    def call(self, call_id: str) -> dict[str, Any] | None:
        return _row(self.db.execute("SELECT * FROM calls WHERE call_id=?",
                                    (call_id,)).fetchone())

    def calls(self, *, status: str | None = None, outcome: str | None = None,
              language: str | None = None, flagged: bool = False, q: str | None = None,
              limit: int = 200) -> list[dict[str, Any]]:
        sql = ("SELECT c.*, r.reason, r.sentiment, r.qa_score FROM calls c "
               "LEFT JOIN reviews r ON r.call_id = c.call_id WHERE 1=1")
        args: list[Any] = []
        if status:
            sql += " AND c.status=?"
            args.append(status)
        if outcome:
            sql += " AND c.outcome LIKE ?"
            args.append(outcome + "%")
        if language:
            sql += " AND c.language=?"
            args.append(language)
        if flagged:
            sql += " AND c.blocks > 0"
        if q:
            sql += (" AND (c.borrower_name LIKE ? OR c.call_id LIKE ? OR c.note LIKE ? OR "
                    "c.call_id IN (SELECT call_id FROM turns WHERE borrower LIKE ? OR agent "
                    "LIKE ?))")
            args += [f"%{q}%"] * 5
        sql += " ORDER BY c.started_utc DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.db.execute(sql, args)]

    def turns(self, call_id: str) -> list[dict[str, Any]]:
        return [_row(r, ("tools", "refused", "replaced")) for r in self.db.execute(
            "SELECT * FROM turns WHERE call_id=? ORDER BY idx", (call_id,))]

    # ---------- traces ----------

    def add_spans(self, spans: list[dict[str, Any]]) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO spans VALUES (?,?,?,?,?,?,?,?,?)",
            [(s["span_id"], s["trace_id"], s.get("parent_id"), s.get("call_id"), s["name"],
              s["start_ns"], s["end_ns"], s.get("status"), json.dumps(s.get("attrs", {})))
             for s in spans])

    def spans(self, call_id: str) -> list[dict[str, Any]]:
        return [_row(r, ("attrs",)) for r in self.db.execute(
            "SELECT * FROM spans WHERE call_id=? ORDER BY start_ns", (call_id,))]

    # ---------- reviews (QA + analytics) ----------

    def save_review(self, call_id: str, review: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?)",
            (call_id, review.get("reason"), review.get("sentiment"), review.get("summary"),
             json.dumps(review.get("qa", [])), review.get("qa_score"),
             json.dumps(review.get("compliance", [])), review.get("model"),
             review.get("seconds"), _now()))

    def review(self, call_id: str) -> dict[str, Any] | None:
        return _row(self.db.execute("SELECT * FROM reviews WHERE call_id=?",
                                    (call_id,)).fetchone(), ("qa", "compliance"))

    def unreviewed(self) -> list[str]:
        return [r[0] for r in self.db.execute(
            "SELECT c.call_id FROM calls c LEFT JOIN reviews r ON r.call_id=c.call_id "
            "WHERE c.status='ended' AND r.call_id IS NULL ORDER BY c.started_utc")]

    def reviews(self) -> list[dict[str, Any]]:
        return [_row(r, ("qa", "compliance")) for r in self.db.execute(
            "SELECT r.*, c.language, c.outcome, c.started_utc FROM reviews r "
            "JOIN calls c ON c.call_id = r.call_id")]

    # ---------- human desk ----------

    def desk_state(self, escalation_id: str) -> dict[str, Any] | None:
        return _row(self.db.execute("SELECT * FROM desk WHERE escalation_id=?",
                                    (escalation_id,)).fetchone())

    def set_desk(self, escalation_id: str, *, team: str, status: str,
                 assignee: str | None = None, resolution: str | None = None) -> None:
        self.db.execute("INSERT OR REPLACE INTO desk VALUES (?,?,?,?,?,?)",
                        (escalation_id, team, status, assignee, resolution, _now()))
