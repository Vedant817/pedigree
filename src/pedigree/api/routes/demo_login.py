"""Local demo login. Off unless PEDIGREE_DEMO_LOGIN is set. Never returns an operator token."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Request

from ...config import validate_tenant
from ...errors import PedigreeError
from .. import auth

_LOCAL_PEERS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def register(app: FastAPI, registry, settings) -> None:
    @app.post("/v1/demo/session")
    def demo_session(request: Request):
        auth.check_peer(request)
        if not settings.pedigree_demo_login:
            raise PedigreeError("demo login is not enabled", code="not_in_graph")
        host = request.client.host if request.client is not None else ""
        if host not in _LOCAL_PEERS:
            raise PedigreeError("demo login is only available from this machine", code="forbidden")
        tenant = validate_tenant(settings.pedigree_demo_tenant)
        path = Path(settings.pedigree_credentials_dir) / f"demo-{tenant}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            raise PedigreeError("demo tenant has no local credential file", code="not_in_graph") from None
        token = payload.get("agent_token") if isinstance(payload, dict) else None
        principal = registry.resolve(token) if isinstance(token, str) else None
        if principal is None or principal.role != "agent" or principal.tenant_id != tenant:
            raise PedigreeError("demo tenant has no local agent credential", code="not_in_graph")
        return {"tenant": tenant, "role": "agent", "token": token}
