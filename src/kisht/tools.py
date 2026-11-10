"""The tools the agent can use. The model decides which to call and when; the guard checks each
call. None of them takes a loan or borrower id: they act on the conversation's own account.

There is deliberately no tool to waive, settle, restructure or confirm a promise: waivers and
the like can only be escalated to a human, and a promise is saved by code only after the
borrower's own clear yes to the read-back.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from kisht.guard import GuardRefused, PolicyGuard


def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required,
                       "additionalProperties": False}}}


TOOL_SCHEMAS: list[dict[str, Any]] = [
    _fn("verify_identity",
        "Check who you are speaking with, before sharing ANY account detail. Ask the person for "
        "their date of birth or their PIN code and pass what they said.",
        {"date_of_birth": {"type": "string", "description": "YYYY-MM-DD"},
         "pincode": {"type": "string", "description": "6-digit PIN code"}}, []),
    _fn("get_dues",
        "After identity is verified: amounts due, days past due, next EMI, open promises, and "
        "the promise limits this lender allows.",
        {}, []),
    _fn("record_promise_to_pay",
        "When the borrower commits to pay an amount on a date. Returns a read_back sentence: say "
        "it to the borrower and wait for their yes. The system saves it after their yes.",
        {"amount": {"type": "integer", "description": "rupees"},
         "pay_date": {"type": "string", "description": "YYYY-MM-DD"}}, ["amount", "pay_date"]),
    _fn("send_payment_link",
        "Send a UPI payment link for an amount to the borrower's registered mobile number.",
        {"amount": {"type": "integer", "description": "rupees"}}, ["amount"]),
    _fn("schedule_followup",
        "Plan the next contact (within 14 days), e.g. the day after a promised date.",
        {"on_date": {"type": "string", "description": "YYYY-MM-DD"},
         "reason": {"type": "string"}}, ["on_date", "reason"]),
    _fn("escalate_to_human",
        "Hand the case to the lender's team. Use for: waiver, settlement, restructure, dispute, "
        "hardship (job loss, illness, cannot pay the minimum), bereavement, wrong_person, "
        "complaint. You cannot decide these yourself.",
        {"reason": {"type": "string", "enum": ["waiver", "settlement", "restructure", "dispute",
                                               "hardship", "bereavement", "wrong_person",
                                               "complaint"]},
         "summary": {"type": "string", "description": "one or two sentences for the team"}},
        ["reason", "summary"]),
    _fn("opt_out",
        "The person asks not to be contacted again. Honour it at once.", {}, []),
]


@dataclass
class ToolResult:
    content: dict[str, Any]

    @property
    def ok(self) -> bool:
        return bool(self.content.get("ok"))

    def as_message(self, tool_call_id: str) -> dict[str, Any]:
        return {"role": "tool", "tool_call_id": tool_call_id,
                "content": json.dumps(self.content, ensure_ascii=False)}


class ToolRunner:
    def __init__(self, guard: PolicyGuard):
        self.guard = guard
        g = guard
        self._dispatch = {
            "verify_identity": lambda c, a: g.verify_identity(
                c, date_of_birth=a.get("date_of_birth"), pincode=a.get("pincode")),
            "get_dues": lambda c, a: g.get_dues(c),
            "record_promise_to_pay": lambda c, a: g.propose_promise(
                c, amount=int(a["amount"]), pay_date=str(a["pay_date"])),
            "send_payment_link": lambda c, a: g.send_payment_link(c, amount=int(a["amount"])),
            "schedule_followup": lambda c, a: g.schedule_followup(
                c, on_date=str(a["on_date"]), reason=str(a["reason"])),
            "escalate_to_human": lambda c, a: g.escalate_to_human(
                c, reason=str(a["reason"]), summary=str(a["summary"])),
            "opt_out": lambda c, a: g.opt_out(c),
        }

    def run(self, call_id: str, name: str, arguments: str) -> ToolResult:
        if name not in self._dispatch:
            return self._bad(call_id, name, f"unknown tool {name!r}")
        try:
            args = json.loads(arguments or "{}")
            if not isinstance(args, dict):
                raise TypeError("arguments must be a JSON object")
            result = self._dispatch[name](call_id, args)
        except GuardRefused as e:
            return ToolResult({"ok": False, "refused": e.code, "message": e.message})
        except (ValueError, KeyError, TypeError) as e:
            return self._bad(call_id, name, f"bad arguments: {e}")
        if name == "record_promise_to_pay":
            return ToolResult({"ok": True, "status": "waiting_for_borrower_yes",
                               "read_back": result["read_back"],
                               "say": f"So you will pay {result['read_back']}. Is that right?"})
        return ToolResult({"ok": True, **result})

    def _bad(self, call_id: str, name: str, message: str) -> ToolResult:
        self.guard.audit.record(call_id=call_id, tenant_id=self.guard.lender.id, action=name,
                                args={}, outcome="error", detail=message)
        return ToolResult({"ok": False, "refused": "bad_request", "message": message})
