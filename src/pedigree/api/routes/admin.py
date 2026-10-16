import hmac

from fastapi import FastAPI, Request

from ...errors import Unauthorized
from ..schemas import TenantCreate


def _require_admin(request: Request, settings) -> None:
    """Fail-closed admin check (P-013): always required, constant-time, no bootstrap bypass.

    There is no `has_tenants()` escape hatch anymore: a fresh deploy is NOT owned by the
    first caller. First-run tenant creation goes through `pedigree admin create-tenant`.
    """
    expected = (settings.pedigree_admin_token or "").encode("utf-8")
    header = request.headers.get("x-admin-token", "").encode("utf-8")
    if not expected or not hmac.compare_digest(header, expected):
        raise Unauthorized("admin token required")


def register(app: FastAPI, registry, settings) -> None:
    @app.post("/admin/tenants")
    def create_tenant(payload: TenantCreate, request: Request):
        _require_admin(request, settings)
        cred = registry.create_tenant(payload.id, payload.node_cap)
        return {"tenant": cred.tenant_id, "token": cred.token}

    @app.get("/admin/tenants")
    def list_tenants(request: Request):
        _require_admin(request, settings)
        return {"tenants": [{"id": r.tenant_id, "status": r.status, "node_cap": r.node_cap} for r in registry.list_tenants()]}
