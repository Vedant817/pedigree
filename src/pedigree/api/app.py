"""FastAPI application factory (F-05). Tenant identity comes only from bearer auth."""

from __future__ import annotations

import contextlib
import threading
import uuid
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.staticfiles import StaticFiles

from ..config import DEV_ENVS, admin_token_problem, get_settings
from ..db.client import Db
from ..errors import PedigreeError
from . import routes
from .registry import TenantRegistry
from .schemas import EventResponse, OkResponse  # noqa: F401


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(PedigreeError)
    async def pedigree(request: Request, exc: PedigreeError):
        return JSONResponse(status_code=exc.http_status,
                            content={"error": {"code": exc.code, "message": str(exc),
                                               "detail": exc.detail,
                                               "correlation_id": getattr(request.state, "correlation_id", None)}})

    @app.exception_handler(Exception)
    async def generic(request: Request, exc: Exception):
        return JSONResponse(status_code=500,
                            content={"error": {"code": "internal", "message": str(exc),
                                               "correlation_id": getattr(request.state, "correlation_id", None)}})


class BodySizeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        cl = request.headers.get("content-length")
        if cl:
            try:
                size = int(cl)
            except (ValueError, TypeError):
                return JSONResponse(status_code=400, content={"error": {"code": "invalid_argument", "message": "invalid content-length"}})
            if size < 0 or size > 256 * 1024:
                return JSONResponse(status_code=413, content={"error": {"code": "too_large", "message": "body too large"}})
        return await call_next(request)


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        cid = request.headers.get("x-correlation-id") or uuid.uuid4().hex
        request.state.correlation_id = cid
        response = await call_next(request)
        response.headers["x-correlation-id"] = cid
        return response


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


def create_app(db: Db | None = None, settings=None) -> FastAPI:
    settings = settings or get_settings()
    problem = admin_token_problem(settings)
    if problem is not None:
        raise RuntimeError(f"refusing to start: {problem}")
    db = db or Db(settings)
    registry = TenantRegistry(db, settings)
    # Function-local import keeps `import pedigree.api.app` free of mcp_server side
    # effects (P-025 covers the rest).
    from ..mcp_server import build_mcp

    mcp_srv = build_mcp(db=db, settings=settings)
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
    app.state.rate_limit = defaultdict(lambda: __import__("collections").deque())
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
