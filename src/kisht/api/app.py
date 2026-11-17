"""Builds the FastAPI app from one router per page. See the package docstring for the routes."""
from __future__ import annotations

import contextlib
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from kisht.api import calls, chat, desk, live, overview, quality, system
from kisht.api.auth import install_login
from kisht.api.common import DIST, SHUTDOWN_WAIT_S, Ctx
from kisht.ports import ModelUnavailable
from kisht.runtime import Runtime

ROUTERS = (system, overview, calls, live, desk, chat, quality)


def create_api(rt: Runtime, tokens: dict[str, str] | None = None) -> FastAPI:
    """`tokens` is {token: role}. None or empty means no login, which `kisht serve` only
    allows with `mode: demo`."""
    ctx = Ctx(rt=rt, tokens=dict(tokens or {}))

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        ctx.background.join(SHUTDOWN_WAIT_S)

    app = FastAPI(title="Kisht contact centre", lifespan=lifespan)
    app.state.ctx = ctx
    install_login(app, ctx.tokens, rt.audit)

    @app.exception_handler(ModelUnavailable)
    async def model_down(_request: Any, exc: ModelUnavailable) -> JSONResponse:
        """A busy or stopped model server is not a server error of ours: say so plainly."""
        return JSONResponse({"detail": f"The model server is not answering: {exc}"}, 503)

    for module in ROUTERS:
        app.include_router(module.router(ctx))

    if DIST.exists():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            # The page shell must never be cached: asset names change on every build.
            return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})

    return app
