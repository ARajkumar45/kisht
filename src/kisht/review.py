"""Post-call review: automatic QA and conversation analytics for every call.

Contact centres score about 2% of calls by hand. Here every call gets:
  - a QA scorecard (the lender's items, default in lender.py): pass / fail / n/a with a short
    quote as evidence. The model judges what needs judgement; code fills in what it knows
    for sure (identity before details is enforced by the guard, so it cannot fail).
  - analytics tags: the reason the borrower is not paying, their mood, a one-line summary.
  - compliance facts from code, not from the model: how many threats, leaks before identity,
    false claims and out-of-policy actions the guard blocked in this call. Each one was an
    attempt by the model that never reached the borrower.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from kisht.insights import InsightsStore
from kisht.lender import Lender
from kisht.ports import ChatModel, ModelUnavailable
from kisht.tracing import call_span, set_attrs

REASONS = ["salary_delay", "job_loss", "medical", "family_emergency", "business_loss",
           "forgot", "dispute", "already_paid", "wants_waiver", "wrong_person",
           "refused_to_engage", "no_issue", "not_stated", "other"]
SENTIMENTS = ["positive", "neutral", "negative", "distressed"]

# Code-side compliance: which blocked actions count under which rule.
COMPLIANCE_RULES = {
    "no_threats": ({"banned_phrase"}, "Threats or shaming"),
    "privacy": ({"leak_before_identity"}, "Loan details before identity"),
    "no_false_claims": ({"false_promise_claim", "unbacked_link_claim", "false_claim"},
                        "Claims only code can make (promise saved, link sent, waiver)"),
    "within_policy": ({"date_out_of_policy", "amount_out_of_policy", "promise_exists",
                       "bad_followup_date"}, "Promises or follow-ups outside lender policy"),
}

PROMPT = """\
You are a quality reviewer in a loan collections contact centre. Review this conversation \
between our agent and a borrower. Be strict and fair.

SCORECARD (judge each item):
{items}

Answer with ONLY a JSON object, no other text:
{{"reason": one of {reasons}: the reason the BORROWER gave for not paying. Use a reason \
only if the borrower said it; if they gave none, use "not_stated". Do not guess,
 "sentiment": one of {sentiments} (the borrower's mood at the end),
 "summary": one sentence in English: situation and outcome,
 "qa": {{"<item id>": {{"result": "pass" | "fail" | "na", "evidence": "a short quote or \
fact"}}, ...one entry per scorecard item}}}}
Use "na" only when the item does not apply (for example no promise was made).

FACTS RECORDED BY CODE (these are certain; your summary and scores must not contradict them):
{facts}

CONVERSATION (tools the agent used are in brackets):
{conversation}
"""


def _conversation(turns: list[dict]) -> str:
    lines = []
    for t in turns:
        if t["borrower"]:
            lines.append(f"Borrower: {t['borrower']}")
        tools = f" [{', '.join(t['tools'])}]" if t.get("tools") else ""
        lines.append(f"Agent{tools}: {t['agent']}")
    return "\n".join(lines)


def facts(call: dict, turns: list[dict]) -> str:
    """What code knows for sure about this call. The first live reviews contradicted the
    record ("failed to verify identity" on a call where identity was verified), so the
    reviewer is told the record up front."""
    verified = next((i for i, t in enumerate(turns) if "verify_identity" in (t.get("tools") or [])
                     and not {"identity_mismatch", "identity_locked"} & set(t.get("refused") or [])),
                    None)
    used = [x for t in turns for x in (t.get("tools") or [])]
    blocked = [x for t in turns for x in (t.get("replaced") or []) + (t.get("refused") or [])]
    lines = [f"- Outcome: {call.get('outcome') or 'unknown'}.",
             (f"- Identity WAS verified, in borrower turn {verified}. Code blocks every loan "
              "detail before that point, so none was shared earlier." if verified is not None
              else "- Identity was never verified, so code shared no loan detail at all."),
             f"- Tools the agent used, in order: {', '.join(used) or 'none'}.",
             ("- A promise to pay was saved." if "promise" in (call.get("outcome") or "")
              else "- No promise to pay was saved."),
             ("- A payment link was sent." if "send_payment_link" in used
              else "- No payment link was sent."),
             (f"- Code blocked or replaced before the borrower heard it: {', '.join(blocked)}."
              if blocked else "- Code blocked nothing.")]
    return "\n".join(lines)


def _parse(text: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("qa"), dict) else None


def compliance(turns: list[dict]) -> list[dict[str, Any]]:
    blocked: list[str] = []
    for t in turns:
        blocked += t.get("replaced") or []
        blocked += t.get("refused") or []
    out = []
    for rule, (codes, label) in COMPLIANCE_RULES.items():
        n = sum(1 for b in blocked if b in codes)
        out.append({"rule": rule, "label": label, "blocked": n,
                    "status": "blocked_attempt" if n else "ok"})
    return out


class Reviewer:
    def __init__(self, model: ChatModel, store: InsightsStore):
        self.model = model
        self.store = store

    def review(self, call_id: str, lender: Lender) -> dict[str, Any]:
        call = self.store.call(call_id)
        turns = self.store.turns(call_id)
        started = time.perf_counter()
        self.store.delete_spans(call_id, "review")           # a re-review replaces the old one
        with call_span(call_id, "review", gen_ai__request__model=self.model.name) as span:
            data = self._ask(lender, call, turns)
            review = self._score(lender, data, turns)
            review["seconds"] = round(time.perf_counter() - started, 2)
            review["model"] = self.model.name
            set_attrs(span, kisht__reason=review["reason"], kisht__qa_score=review["qa_score"],
                      kisht__parsed=data is not None)
        self.store.save_review(call_id, review)
        return review

    def _ask(self, lender: Lender, call: dict, turns: list[dict]) -> dict | None:
        prompt = PROMPT.format(
            items="\n".join(f"- {q.id}: {q.check}" for q in lender.qa_scorecard),
            reasons=json.dumps(REASONS), sentiments=json.dumps(SENTIMENTS),
            facts=facts(call, turns), conversation=_conversation(turns))
        messages = [{"role": "user", "content": prompt}]
        for _ in range(2):
            try:
                reply = self.model.complete(messages)
            except ModelUnavailable:
                return None
            data = _parse(reply.content)
            if data:
                return data
            messages += [{"role": "assistant", "content": reply.content or ""},
                         {"role": "user", "content": "Return only the JSON object."}]
        return None

    def _score(self, lender: Lender, data: dict | None, turns: list[dict]) -> dict[str, Any]:
        data = data or {}
        raw = data.get("qa") or {}
        qa = []
        for item in lender.qa_scorecard:
            got = raw.get(item.id) if isinstance(raw.get(item.id), dict) else {}
            result = str(got.get("result", "na")).lower()
            if result not in ("pass", "fail", "na"):
                result = "na"
            entry = {"id": item.id, "check": item.check, "result": result,
                     "evidence": str(got.get("evidence", ""))[:200], "by": "model"}
            if item.id == "verified_first":
                entry.update(result="pass", by="code",
                             evidence="Enforced by the guard: loan details are blocked until "
                                      "identity is verified.")
            qa.append(entry)
        scored = [q for q in qa if q["result"] != "na"]
        qa_score = (round(100 * sum(q["result"] == "pass" for q in scored) / len(scored), 1)
                    if scored and data else None)
        reason = data.get("reason") if data.get("reason") in REASONS else "other"
        sentiment = data.get("sentiment") if data.get("sentiment") in SENTIMENTS else "neutral"
        return {"reason": reason if data else "unknown", "sentiment": sentiment,
                "summary": str(data.get("summary", "Review failed: no valid answer."))[:400],
                "qa": qa, "qa_score": qa_score, "compliance": compliance(turns)}
