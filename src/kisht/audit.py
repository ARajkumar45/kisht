"""Audit log: one record for every tool call and every guard decision (D46).

Personal data is masked before it is written (D56): phone numbers keep their last 4 digits.
Fix vs the receptionist version: dates such as 2026-11-10 were masked as phone numbers.
A phone number here means 10-13 digits, optionally with + and single spaces or hyphens.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_PHONE = re.compile(r"(?<![\w-])\+?\d(?:[ -]?\d){9,12}(?![\w-])")
OUTCOMES = {"ok", "denied", "error"}


def mask_phone(text: str) -> str:
    """'+91 98450 12345' -> '******2345'. Dates, amounts and loan ids are left alone."""
    def _mask(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group())
        return "*" * 6 + digits[-4:]
    return _PHONE.sub(_mask, text)


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return mask_phone(value)
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_redact(v) for v in value]
    return value


def entries_for_call(audit_dir: str | Path, call_id: str) -> list[dict[str, Any]]:
    """A call's audit trail from the files on disk. Each process (chat, voice bridge,
    simulator, dashboard) writes its own file, so one process's memory is never the whole
    story."""
    out: list[dict[str, Any]] = []
    for path in sorted(Path(audit_dir).glob("*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if call_id not in line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("call_id") == call_id:
                    out.append(entry)
    return sorted(out, key=lambda e: e["time"])


class AuditLog:
    def __init__(self, path: str | Path | None = None):
        self.entries: list[dict[str, Any]] = []
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, *, call_id: str | None, tenant_id: str, action: str,
               args: dict[str, Any], outcome: str, detail: str = "") -> dict[str, Any]:
        if outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome {outcome!r}")
        entry = {
            "time": datetime.now(UTC).isoformat(),
            "call_id": call_id,
            "tenant_id": tenant_id,
            "action": action,
            "args": _redact(args),
            "outcome": outcome,
            "detail": _redact(detail),
        }
        self.entries.append(entry)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def for_call(self, call_id: str) -> list[dict[str, Any]]:
        return [e for e in self.entries if e["call_id"] == call_id]

    def telemetry(self, entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Guard telemetry: how often the agent acted, and how often a rule stopped it."""
        entries = self.entries if entries is None else entries
        actions: dict[str, dict[str, int]] = {}
        blocked_by_rule: dict[str, int] = {}
        for e in entries:
            row = actions.setdefault(e["action"], {"ok": 0, "denied": 0, "error": 0})
            row[e["outcome"]] += 1
            if e["outcome"] == "denied":
                rule = (e["detail"] or "unknown").split(":", 1)[0]
                blocked_by_rule[rule] = blocked_by_rule.get(rule, 0) + 1
        return {"actions": actions, "blocked_by_rule": blocked_by_rule}
