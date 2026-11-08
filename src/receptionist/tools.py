"""The tools the model may call. Every tool goes through the guard (D42).

The model sees two tools: check_availability and book_visit.
book_visit only *proposes*: it returns a read-back sentence for the caller.
The booking itself is made by session code when the caller says yes (D43, D44);
the model has no tool for that, so it can never book on its own.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from receptionist.guard import Guard, GuardRefused

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "check_availability",
        "description": "List free start times for a service on one day. Call this before "
                       "talking about any free time. If the caller named a time, pass it as "
                       "preferred_time to get the free times closest to it.",
        "parameters": {"type": "object", "properties": {
            "service_id": {"type": "string", "description": "Service id from the business knowledge"},
            "day": {"type": "string", "description": "YYYY-MM-DD"},
            "preferred_time": {"type": "string", "description": "Optional, HH:MM (24-hour)"},
            "staff_id": {"type": "string", "description": "Optional: a specific staff member"},
        }, "required": ["service_id", "day"]}}},
    {"type": "function", "function": {
        "name": "book_visit",
        "description": "Propose a booking once you have the service, start time, caller's name "
                       "and phone. Returns read_back: say it to the caller exactly, then wait. "
                       "The system books it when the caller says yes; you never confirm "
                       "bookings yourself.",
        "parameters": {"type": "object", "properties": {
            "service_id": {"type": "string"},
            "start": {"type": "string", "description": "YYYY-MM-DDTHH:MM local time"},
            "customer_name": {"type": "string"},
            "customer_phone": {"type": "string"},
            "staff_id": {"type": "string", "description": "Optional: a specific staff member"},
        }, "required": ["service_id", "start", "customer_name", "customer_phone"]}}},
]

REQUIRED_FOR_BOOKING = ("service_id", "start", "customer_name", "customer_phone")


@dataclass
class ToolResult:
    content: dict[str, Any]     # goes back to the model as JSON

    def as_message(self, tool_call_id: str) -> dict[str, Any]:
        return {"role": "tool", "tool_call_id": tool_call_id,
                "content": json.dumps(self.content, ensure_ascii=False)}


class ToolRunner:
    def __init__(self, guard: Guard):
        self.guard = guard

    def run(self, call_id: str, name: str, arguments: str | dict) -> ToolResult:
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
        except (ValueError, TypeError):
            args = None
        if not isinstance(args, dict):
            return self._error(call_id, name, {"raw": str(arguments)[:200]},
                               "Arguments were not a valid JSON object. Try again.")
        try:
            if name == "check_availability":
                found = self.guard.check_availability(
                    call_id, service_id=str(args.get("service_id", "")),
                    day=str(args.get("day", "")),
                    preferred_time=args.get("preferred_time") or None,
                    staff_id=args.get("staff_id") or None)
                note = "No free times that day." if not found["slots"] else ""
                return ToolResult({"ok": True, **found, "note": note})
            if name == "book_visit":
                missing = [k for k in REQUIRED_FOR_BOOKING if not args.get(k)]
                if missing:
                    return ToolResult({"ok": False, "refused": "missing_fields",
                                       "message": "Ask the caller for: " + ", ".join(missing)})
                pending = self.guard.propose_booking(
                    call_id, service_id=str(args["service_id"]), start=str(args["start"]),
                    customer_name=str(args["customer_name"]),
                    customer_phone=str(args["customer_phone"]),
                    staff_id=args.get("staff_id") or None)
                return ToolResult({"ok": True, "status": "waiting_for_caller_yes",
                                   "read_back": pending["read_back"]})
        except GuardRefused as e:
            return ToolResult({"ok": False, "refused": e.code, "message": e.message})
        return self._error(call_id, name, args, f"Unknown tool {name!r}.")

    def _error(self, call_id: str, name: str, args: dict, message: str) -> ToolResult:
        self.guard.audit.record(call_id=call_id, business_id=self.guard.business.business_id,
                                action=name or "unknown", args=args, outcome="error",
                                detail=message)
        return ToolResult({"ok": False, "refused": "bad_request", "message": message})
