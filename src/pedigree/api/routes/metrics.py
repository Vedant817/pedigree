"""Metrics route (protected behind the admin/operator token)."""
from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

from ...config import get_settings
from ...errors import Unauthorized


def register(app: FastAPI, settings=None) -> None:
    settings = settings or get_settings()

    @app.get("/metrics")
    async def metrics(request: Request) -> Response:
        expected = (settings.pedigree_admin_token or "").strip()
        presented = request.headers.get("x-admin-token", "").strip()
        if not expected or not presented or not __import__("hmac").compare_digest(presented, expected):
            raise Unauthorized("admin token required")
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
