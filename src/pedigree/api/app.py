"""FastAPI application factory (F-05). Tenant identity comes only from bearer auth."""

from __future__ import annotations

import contextlib
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from ..config import DEV_ENVS, admin_token_problem, get_settings
from ..db.client import Db
from ..diagnostics import (
    correlation_id,
    error_payload,
    log_typed_rejection,
    log_validation_failure,
    unexpected_error,
)
from ..errors import PedigreeError
from ..http_boundary import BodySizeMiddleware
from ..rate_limit import RateLimiter
from . import routes
from .registry import TenantRegistry
from .schemas import EventResponse, OkResponse  # noqa: F401


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(PedigreeError)
    async def pedigree(request: Request, exc: PedigreeError):
        retry = exc.detail.get("retry_after") if isinstance(exc.detail, dict) else None
        headers = None
        if exc.code == "rate_limited":
            retry = retry if type(retry) is int and 0 < retry < 10**15 else 1
            headers = {"Retry-After": str(retry)}
        cid = getattr(request.state, "correlation_id", None)
        log_typed_rejection(cid, exc)
        return JSONResponse(status_code=exc.http_status, content={"error": error_payload(
            exc, cid)}, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError):
        cid = getattr(request.state, "correlation_id", None) or correlation_id()
        log_validation_failure(cid, exc)
        return JSONResponse(status_code=422, content={"error": {
            "code": "invalid_argument", "message": "invalid argument",
            "correlation_id": cid}})

    @app.exception_handler(Exception)
    async def generic(request: Request, exc: Exception):
        error = unexpected_error(exc, "http_request", getattr(request.state, "correlation_id", None))
        return JSONResponse(status_code=500, content={"error": error},
                            headers={"x-correlation-id": error["correlation_id"]})


class CorrelationMiddleware:
    """Contain request failures before Starlette rethrows them to server logging."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cid = correlation_id()
        scope.setdefault("state", {})["correlation_id"] = cid
        started = finished = False

        async def correlated_send(message):
            nonlocal started, finished
            if message["type"] == "http.response.start":
                started = True
                message = {**message, "headers": [
                    (name, value) for name, value in message.get("headers", ())
                    if name.lower() != b"x-correlation-id"
                ] + [(b"x-correlation-id", cid.encode("ascii"))]}
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                finished = True
            await send(message)

        try:
            await self.app(scope, receive, correlated_send)
        except Exception as exc:  # noqa: BLE001 - the public failure boundary
            error = unexpected_error(exc, "http_request", cid)
            if not started:
                await JSONResponse(status_code=500, content={"error": error})(scope, receive, correlated_send)
            elif not finished:
                # A streaming response has already committed its status. Never emit
                # a second response or rethrow a secret-bearing cause to the server.
                with contextlib.suppress(Exception):
                    await correlated_send({"type": "http.response.body", "body": b"", "more_body": False})


class RootDispatcher:
    """Serve the UI at / and the MCP streamable-HTTP app at /mcp (P-016).

    The MCP ASGI app's own route is "/mcp" and it must see the original path, so
    requests under /mcp are passed through unchanged (docs/02-ARCHITECTURE.md:50;
    spike docs/tech/examples/mcp/mount_in_fastapi.py, mcp 2.3.0).
    """

    def __init__(self, mcp_app, static_app) -> None:
        self._mcp_app = mcp_app
        self._static_app = static_app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope["path"].startswith("/mcp"):
            await self._mcp_app(scope, receive, send)
        else:
            await self._static_app(scope, receive, send)


def _startup_resume(db: Db, registry: TenantRegistry) -> None:
    """P-011: finish any crashed (`status='running'`) revocations, off the request path."""
    import logging

    from ..config import graph_name
    from ..engine.revoke import reconcile, resume_incomplete  # function-local: side-effect free

    log = logging.getLogger("pedigree.resume")
    try:
        for rec in registry.list_tenants():
            try:
                gname = graph_name(rec.tenant_id)
                done = resume_incomplete(db, gname)
                if done:
                    log.info("startup-resume: finished %d revocation(s) for tenant %s",
                             len(done), rec.tenant_id)
                rec_res = reconcile(db, gname)
                if rec_res.get("reconciled"):
                    log.info("startup-reconcile: repaired %s quarantined nodes for tenant %s",
                             rec_res.get("reconciled"), rec.tenant_id)
            except Exception:  # noqa: BLE001
                log.warning("startup-resume: failed for tenant %s", rec.tenant_id,
                           exc_info=True)
    except Exception:  # noqa: BLE001
        log.warning("startup-resume: scan failed", exc_info=True)


def _docs_url(settings: object) -> str | None:
    if settings.pedigree_env.lower() in DEV_ENVS or getattr(settings, "pedigree_public_docs", False):
        return "/docs"
    return None


def create_app(db: Db | None = None, settings=None, *, limiter: RateLimiter | None = None) -> FastAPI:
    settings = settings or get_settings()
    problem = admin_token_problem(settings)
    if problem is not None:
        raise RuntimeError(f"refusing to start: {problem}")
    db = db or Db(settings)
    registry = TenantRegistry(db, settings)
    # Function-local import keeps `import pedigree.api.app` free of mcp_server side
    # effects (P-025 covers the rest).
    from ..mcp_server import build_mcp

    limiter = limiter if limiter is not None else RateLimiter()
    mcp_srv = build_mcp(db=db, settings=settings, limiter=limiter)
    mcp_app = mcp_srv.server.streamable_http_app()

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp_srv.server.session_manager.run():
            threading.Thread(
                target=_startup_resume, args=(db, registry), daemon=True,
                name="pedigree-startup-resume",
            ).start()
            yield

    docs_url = _docs_url(settings)
    app = FastAPI(
        title="Pedigree API", version="0.1.0", lifespan=lifespan, docs_url=docs_url,
        redoc_url="/redoc" if docs_url else None,
        openapi_url="/openapi.json" if docs_url else None,
    )
    app.state.db = db
    app.state.settings = settings
    app.state.registry = registry
    app.state.limiter = limiter
    _register_error_handlers(app)
    app.add_middleware(BodySizeMiddleware)
    app.add_middleware(CorrelationMiddleware)
    routes.health.register(app, db)
    routes.admin.register(app, registry, settings)
    routes.metrics.register(app, settings)
    routes.engine.register(app, db, registry, settings)
    routes.events.register(app, db, registry, settings)
    routes.gate.register(app, db, registry, settings)
    routes.workspace.register(app, db)
    ui = StaticFiles(directory=Path(__file__).resolve().parents[1] / "ui", html=True)
    app.mount("/", RootDispatcher(mcp_app, ui), name="workspace")
    return app
