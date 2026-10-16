"""Admin and engine route registration (F-05). Dependencies inject tenant from bearer auth."""

from __future__ import annotations

import typing as t

from fastapi import Request

from ..config import graph_name
from ..db.schema import ensure_schema, node_count
from ..errors import PedigreeError


def _ensure(db, gname):
    ensure_schema(db, gname)


def _engine_context(request):
    return request.state.tenant_id, request.app.state.db


def _gate_rate(request, tenant, settings, action="write"):
    app_state = request.app.state
    key = f"{tenant}:{action}"
    # Lazy local closure with per-tenant deque in app_state.rate_limit
    now = __import__("time").monotonic()
    samples = app_state.rate_limit[key]
    while samples and samples[0] <= now - 60:
        samples.popleft()
    if action == "revoke":
        limit = 10
    else:
        limit = 120
    if len(samples) >= limit:
        raise PedigreeError("rate limited", code="rate_limited", detail={"limit": limit})
    samples.append(now)

def _check_quota(db, gname, cap):
    n = node_count(db, gname)
    if n >= cap:
        raise PedigreeError("quota exceeded", code="quota_exceeded", detail={"nodes": n, "cap": cap})


class _AuthResult(t.TypedDict):
    tenant_id: str

def authenticate(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise PedigreeError("missing or invalid Authorization", code="unauthorized")
    raw = auth.removeprefix("Bearer ")
    token = raw.strip()
    if (not token) or (token != raw) or (" " in raw):
        raise PedigreeError("missing or invalid Authorization", code="unauthorized")
    registry = request.app.state.registry
    rec = registry.resolve(token)
    if rec is None:
        raise PedigreeError("invalid token", code="unauthorized", detail={})
    if rec.status != "active":
        raise PedigreeError("tenant revoked", code="forbidden")
    tenant = rec.tenant_id
    db = request.app.state.db
    gname = graph_name(tenant)
    ensure_schema(db, gname)
    request.state.tenant_id = tenant
    request.state.graph_name = gname
    request.state.principal = rec
    _gate_rate(request, tenant, request.app.state.settings)
    return tenant


def require_operator(request: Request) -> None:
    if getattr(getattr(request.state, "principal", None), "role", None) != "operator":
        raise PedigreeError("operator credential required", code="forbidden")


def authorize_source(principal, kind, integrity) -> None:
    """Shared REST/MCP trust policy; ordinary captures remain untrusted for agents."""
    if principal.role != "operator" and (kind in ("human", "scanner") or integrity == "trusted"):
        raise PedigreeError("trusted source requires operator credential", code="forbidden")


def set_tenant(request, tenant):
    request.state.tenant_id = tenant
    return tenant

def get_tenant(request: Request) -> str:
    tid = getattr(request.state, "tenant_id", None)
    if tid is None:
        raise PedigreeError("not authenticated", code="unauthorized")
    return tid

def tenant_from_request(request: Request) -> str:
    return get_tenant(request)
