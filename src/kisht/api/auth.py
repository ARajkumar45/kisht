"""Login and roles. Each request to /api/ carries a bearer token; the token's role decides
what it may do. Viewer < agent < supervisor: each can do what the ones before it can."""
from __future__ import annotations

import hmac
import os
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from kisht.audit import AuditLog

ROLES = ("viewer", "agent", "supervisor")
SUPERVISOR_ONLY = re.compile(r"^/api/(export/|calls/[^/]+/(coach|takeover|qa)$)")
OPEN_PATHS = frozenset({"/api/health"})
MIN_TOKEN = 16


def load_api_tokens(env: str | None = None) -> dict[str, str]:
    """KISHT_API_TOKENS="viewer:<token>,agent:<token>,supervisor:<token>" -> {token: role}.
    A token shorter than 16 characters or an unknown role stops the start: a weak login
    that looks like a login is worse than none."""
    raw = os.environ.get("KISHT_API_TOKENS", "") if env is None else env
    out: dict[str, str] = {}
    for part in filter(None, (x.strip() for x in raw.split(","))):
        role, _, token = part.partition(":")
        if role not in ROLES or len(token) < MIN_TOKEN:
            raise ValueError("KISHT_API_TOKENS: each entry is role:token, role one of "
                             f"{', '.join(ROLES)}, token at least {MIN_TOKEN} characters")
        out[token] = role
    return out


def needed_role(method: str, path: str) -> str:
    """Reading is for viewers. Working a case or a chat is for agents. Steering a live call,
    grading one, or taking borrower data out as a file is for supervisors."""
    if SUPERVISOR_ONLY.match(path):
        return "supervisor"
    return "viewer" if method in ("GET", "HEAD", "OPTIONS") else "agent"


def role_for(tokens: dict[str, str], given: str) -> str | None:
    """Compares against every token in constant time, so timing says nothing about which
    token was close."""
    found = None
    for token, role in tokens.items():
        if hmac.compare_digest(token.encode(), given.encode()):
            found = role
    return found


def install_login(app: FastAPI, tokens: dict[str, str], audit: AuditLog) -> None:
    """No tokens means no login, which `kisht serve` only allows with `mode: demo`."""
    if not tokens:
        return

    @app.middleware("http")
    async def login(request: Request, call_next: Any) -> Any:
        path = request.url.path
        if not path.startswith("/api/") or path in OPEN_PATHS:
            return await call_next(request)
        given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        role = role_for(tokens, given)
        if role is None:
            return JSONResponse({"detail": "Sign in: a valid access token is needed."}, 401,
                                headers={"WWW-Authenticate": "Bearer"})
        need = needed_role(request.method, path)
        if ROLES.index(role) < ROLES.index(need):
            audit.record(tenant_id="-", call_id=None, action="api_denied",
                         args={"role": role, "needs": need, "path": path}, outcome="denied")
            return JSONResponse({"detail": f"This needs the {need} role; you are signed in "
                                           f"as {role}."}, 403)
        request.state.role = role
        return await call_next(request)


def role_of(request: Request) -> str:
    """Without tokens (demo) everyone is a supervisor."""
    return getattr(request.state, "role", ROLES[-1])
