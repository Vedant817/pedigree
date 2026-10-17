"""Metrics route (protected behind the admin/operator token)."""
from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

from ...config import get_settings
from .admin import _require_admin


def register(app: FastAPI, settings=None) -> None:
    settings = settings or get_settings()

    @app.get("/metrics")
    async def metrics(request: Request) -> Response:
        _require_admin(request, settings)
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
