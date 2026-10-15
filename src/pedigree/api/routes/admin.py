from fastapi import FastAPI, Request

from ...errors import Unauthorized
from ..schemas import TenantCreate


def register(app: FastAPI, registry, settings) -> None:
    @app.post("/admin/tenants")
    def create_tenant(payload: TenantCreate, request: Request):
        if registry.has_tenants():
            expected = settings.pedigree_admin_token or ""
            header = request.headers.get("x-admin-token", "")
            if not expected or header != expected:
                raise Unauthorized("admin token required")
        cred = registry.create_tenant(payload.id, payload.node_cap)
        return {"tenant": cred.tenant_id, "token": cred.token}

    @app.get("/admin/tenants")
    def list_tenants(request: Request):
        if registry.has_tenants():
            expected = settings.pedigree_admin_token or ""
            header = request.headers.get("x-admin-token", "")
            if not expected or header != expected:
                raise Unauthorized("admin token required")
        return {"tenants": [{"id": r.tenant_id, "status": r.status, "node_cap": r.node_cap} for r in registry.list_tenants()]}
