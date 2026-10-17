"""Admin and engine route registration (F-05). Dependencies inject tenant from bearer auth."""

from __future__ import annotations

from fastapi import Request

from ..config import graph_name
from ..db.schema import ensure_schema
from ..errors import PedigreeError


def peer(request: Request) -> str:
    """ASGI transport peer; shipped servers disable proxy-header rewriting."""
    return request.client.host if request.client is not None else "local:http"


def check_peer(request: Request) -> str:
    identity = peer(request)
    request.app.state.limiter.check_peer(identity)
    return identity


def failed_auth(request: Request, message: str) -> None:
    request.app.state.limiter.failed_auth(peer(request))
    raise PedigreeError(message, code="unauthorized")


def authenticate(request: Request):
    check_peer(request)
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        failed_auth(request, "missing or invalid Authorization")
    raw = authorization.removeprefix("Bearer ")
    token = raw.strip()
    if not token or token != raw or any(char.isspace() for char in raw):
        failed_auth(request, "missing or invalid Authorization")
    registry = request.app.state.registry
    principal = registry.resolve(token)
    if principal is None:
        failed_auth(request, "invalid token")
    if principal.status != "active":
        raise PedigreeError("tenant revoked", code="forbidden")
    tenant = principal.tenant_id
    request.state.tenant_id = tenant
    request.state.graph_name = graph_name(tenant)
    request.state.principal = principal
    return tenant


def admit(request: Request, operation: str, *, dry_run: bool = False,
          record: bool = False) -> None:
    request.app.state.limiter.admit(request.state.tenant_id, operation,
                                   dry_run=dry_run, record=record)
    ensure_schema(request.app.state.db, request.state.graph_name)


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
