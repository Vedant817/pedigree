import hmac

from fastapi import FastAPI, Request

from ...config import graph_name
from ...errors import Unauthorized
from ..schemas import ResumeRequest, TenantCreate


def _require_admin(request: Request, settings) -> None:
    expected = (settings.pedigree_admin_token or "").encode("utf-8")
    header = request.headers.get("x-admin-token", "").encode("utf-8")
    if not expected or not hmac.compare_digest(header, expected):
        raise Unauthorized("admin token required")


def register(app: FastAPI, registry, settings) -> None:
    from ...engine.revoke import resume_incomplete

    @app.post("/admin/tenants")
    def create_tenant(payload: TenantCreate, request: Request):
        _require_admin(request, settings)
        cred = registry.create_tenant(payload.id, payload.node_cap)
        return {"tenant": cred.tenant_id, "token": cred.token}

    @app.post("/v1/admin/resume")
    def resume(payload: ResumeRequest, request: Request):
        _require_admin(request, settings)
        record = registry.get_record(payload.tenant)  # raises NotFoundInGraph if unknown
        gname = graph_name(record.tenant_id)
        done = resume_incomplete(registry.db, gname)
        return {"tenant": record.tenant_id, "resumed": done}

    @app.get("/admin/tenants")
    def list_tenants(request: Request):
        _require_admin(request, settings)
        return {"tenants": [{"id": r.tenant_id, "status": r.status, "node_cap": r.node_cap} for r in registry.list_tenants()]}
