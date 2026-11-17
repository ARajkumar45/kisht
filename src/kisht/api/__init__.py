"""The contact-centre API behind the dashboard. Everything here reads the same stores the agent
writes (ledger, insights) and acts through the same guard, so the dashboard shows the real
system and a human desk action is as audited as an agent action.

    GET  /api/compliance          each recovery-conduct rule, where it is enforced, blocks so far
    GET  /api/overview            KPIs, outcomes, reasons, mood, QA, compliance, speed
    GET  /api/plan                today's planner queue and what happened to each account
    GET  /api/calls               call log (filters: status, outcome, language, flagged, q)
    GET  /api/calls/{id}          transcript, trace spans, review, ledger actions
    GET  /api/live                live calls and alerts (supervisor view)
    GET  /api/desk                escalations for the human desk, routed to teams
    POST /api/desk/{id}           assign / resolve
    POST /api/desk/{id}/assist    agent assist: brief, next best action, suggested replies
    POST /api/assist/ask          answer a question from the loan agreement, with sections
    GET  /api/borrowers           synthetic borrowers, to start a chat
    POST /api/chat/start | /api/chat/{id}/say | /api/chat/{id}/end   test chat as a borrower
    GET  /api/quality             eval results, per-item QA pass rates, AI-vs-human agreement
    POST /api/calls/{id}/coach    supervisor: a private note for the agent's next reply
    POST /api/calls/{id}/takeover supervisor: stop the AI, hand the case to the human desk
    POST /api/calls/{id}/qa       a human's own QA marks for a call (calibrates the AI reviewer)
    GET  /api/export/calls.csv    the call log as a spreadsheet (same filters as /api/calls)

One module per page; each exposes router(ctx). Shared pieces live in common.py, login in
auth.py, and app.py puts them together.
"""
from kisht.api.app import create_api
from kisht.api.auth import ROLES, load_api_tokens, needed_role
from kisht.api.common import DIST, ROOT, SHUTDOWN_WAIT_S, csv_safe

__all__ = ["DIST", "ROLES", "ROOT", "SHUTDOWN_WAIT_S", "create_api", "csv_safe",
           "load_api_tokens", "needed_role"]
