from __future__ import annotations

from fastapi import FastAPI, Request

from ...db.client import Trace
from ...engine.gate import check_action
from ...engine.quota import QuotaPolicy
from .. import auth
from ..schemas import GateRequest


def register(app: FastAPI, db, registry, settings) -> None:
    @app.post("/v1/gate")
    def gate(payload: GateRequest, request: Request):
        auth.authenticate(request)
        tenant = request.state.tenant_id
        gname = request.state.graph_name
        auth.admit(request, "gate", record=payload.record)
        trace = Trace()
        result = check_action(
            db,
            gname,
            action=payload.action.model_dump(),
            tenant=tenant,
            quota=QuotaPolicy(tenant, registry.get_record(tenant).node_cap),
            relied_on=payload.relied_on,
            session_id=payload.session_id,
            policy_path=settings.pedigree_policy_file,
            max_depth=payload.max_depth,
            record=payload.record,
            trace=trace,
        )
        result["trace"] = trace.as_list()
        return result
