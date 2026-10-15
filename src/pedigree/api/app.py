"""FastAPI application factory (F-05). Tenant identity comes only from bearer auth."""

from __future__ import annotations

import uuid
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import get_settings
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
        if cl and int(cl) > 256 * 1024:
            return JSONResponse(status_code=413, content={"error": {"code": "too_large", "message": "body too large"}})
        return await call_next(request)


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        cid = request.headers.get("x-correlation-id") or uuid.uuid4().hex
        request.state.correlation_id = cid
        response = await call_next(request)
        response.headers["x-correlation-id"] = cid
        return response


def create_app(db: Db | None = None, settings=None) -> FastAPI:
    settings = settings or get_settings()
    db = db or Db(settings)
    registry = TenantRegistry(db, settings)
    app = FastAPI(title="Pedigree API", version="0.1.0")
    app.state.db = db
    app.state.settings = settings
    app.state.registry = registry
    app.state.rate_limit = defaultdict(lambda: __import__("collections").deque())
    _register_error_handlers(app)
    app.add_middleware(BodySizeMiddleware)
    app.add_middleware(CorrelationMiddleware)
    routes.health.register(app, db)
    routes.admin.register(app, registry, settings)
    routes.metrics.register(app)
    routes.engine.register(app, db, registry, settings)
    return app


app = create_app()
