from __future__ import annotations

import time

from fastapi import FastAPI, Request

from ...config import graph_name
from ...db.schema import ensure_schema, node_count
from ...engine.blame import blame as run_blame
from ...engine.blame import impact as run_impact
from ...engine.ingest import corroborate, ensure_session, record_action, record_source, remember, session_read
from ...engine.revoke import reinstate, report, revoke
from ...errors import PedigreeError, QuotaExceeded
from .. import auth
from ..schemas import (
    ActionCreate,
    CorroborateRequest,
    EnsureSessionRequest,
    MemoryCreate,
    ReinstateRequest,
    RevokeRequest,
    SessionReadRequest,
    SourceCreate,
)


def register(app: FastAPI, db, registry, settings) -> None:
    def gate(request: Request, tenant: str, kind: str = "write") -> None:
        now = time.monotonic()
        state = app.state.rate_limit
        samples = state[f"{tenant}:{kind}"]
        while samples and samples[0] <= now - 60:
            samples.popleft()
        limit = 10 if kind == "revoke" else 120
        if len(samples) >= limit:
            raise PedigreeError("rate limited", code="rate_limited", detail={"limit": limit})
        samples.append(now)

    def tenant_and_db(request: Request):
        tenant = auth.authenticate(request)
        gname = graph_name(tenant)
        ensure_schema(db, gname)
        return tenant, gname

    def quota(db, gname, tenant):
        cap = registry.get_record(tenant).node_cap
        n = node_count(db, gname)
        if n >= cap:
            raise QuotaExceeded("node cap exceeded", detail={"nodes": n, "cap": cap})

    @app.post("/v1/sources")
    def create_source(payload: SourceCreate, request: Request):
        tenant, gname = tenant_and_db(request)
        gate(request, tenant)
        quota(db, gname, tenant)
        res = record_source(
            db, gname, tenant,
            kind=payload.kind,
            uri=payload.uri,
            title=payload.title,
            content_hash=payload.content_hash,
            integrity=payload.integrity,
            conf=payload.conf,
            id=payload.id,
        )
        return {"id": res.id, "status": res.status, "low_integrity": res.low_integrity,
                "conf_eff": res.conf_eff, "warnings": res.warnings}

    @app.post("/v1/memories")
    def create_memory(payload: MemoryCreate, request: Request):
        tenant, gname = tenant_and_db(request)
        gate(request, tenant)
        quota(db, gname, tenant)
        res = remember(
            db, gname, tenant,
            text=payload.text,
            mkind=payload.mkind,
            derived_from=payload.derived_from,
            corroborated_by=payload.corroborated_by,
            artifact=payload.artifact,
            artifact_key=payload.artifact_key,
            content_hash=payload.content_hash,
            conf=payload.conf,
            agent_id=payload.agent_id,
            session_id=payload.session_id,
            id=payload.id,
            via=payload.via,
        )
        return {"id": res.id, "status": res.status, "low_integrity": res.low_integrity,
                "conf_eff": res.conf_eff, "warnings": res.warnings}

    @app.post("/v1/actions")
    def create_action(payload: ActionCreate, request: Request):
        tenant, gname = tenant_and_db(request)
        gate(request, tenant)
        quota(db, gname, tenant)
        res = record_action(
            db, gname, tenant,
            tool=payload.tool,
            summary=payload.summary,
            relied_on=payload.relied_on,
            decision=payload.decision,
            effect=payload.effect,
            risk=payload.risk,
            artifacts=payload.artifacts,
            artifact_key=payload.artifact_key,
            session_id=payload.session_id,
            agent_id=payload.agent_id,
            id=payload.id,
            via=payload.via,
        )
        return {"id": res.id, "status": res.status, "low_integrity": res.low_integrity,
                "conf_eff": res.conf_eff, "warnings": res.warnings}

    @app.post("/v1/corroborate")
    def do_corroborate(payload: CorroborateRequest, request: Request):
        tenant, gname = tenant_and_db(request)
        gate(request, tenant)
        corroborate(db, gname, payload.memory_id, payload.source_id, by=payload.by)
        return {"ok": True}

    @app.post("/v1/sessions")
    def ensure(payload: EnsureSessionRequest, request: Request):
        tenant, gname = tenant_and_db(request)
        sid = ensure_session(db, gname, tenant, payload.session_id, runtime=payload.runtime, agent_id=payload.agent_id)
        return {"session_id": sid}

    @app.post("/v1/sessions/read")
    def sread(payload: SessionReadRequest, request: Request):
        tenant, gname = tenant_and_db(request)
        if payload.ensure == "yes":
            ensure_session(db, gname, tenant, payload.session_id, runtime=payload.runtime)
        session_read(db, gname, payload.session_id, payload.node_id)
        return {"ok": True}

    @app.post("/v1/revoke")
    def do_revoke(payload: RevokeRequest, request: Request):
        tenant, gname = tenant_and_db(request)
        gate(request, tenant, "revoke")
        gate(request, tenant)  # establish sane consistent state
        out = revoke(db, gname, tenant, root_id=payload.root_id, reason=payload.reason,
                    dry_run=payload.dry_run, kind=payload.kind)
        return out

    @app.post("/v1/reinstate")
    def do_reinstate(payload: ReinstateRequest, request: Request):
        tenant, gname = tenant_and_db(request)
        gate(request, tenant)
        out = reinstate(db, gname, tenant, root_id=payload.root_id, dry_run=payload.dry_run)
        return out

    @app.get("/v1/blame/{node_id}")
    def get_blame(node_id: str, max_depth: int = 12, request: Request = None):
        tenant, gname = tenant_and_db(request)
        result = run_blame(db, gname, node_id, max_depth=max_depth)
        return result

    @app.get("/v1/impact/{node_id}")
    def get_impact(node_id: str, max_depth: int = 12, request: Request = None):
        tenant, gname = tenant_and_db(request)
        result = run_impact(db, gname, node_id, max_depth=max_depth)
        return result

    @app.get("/v1/graph")
    def graph_summary(request: Request):
        tenant, gname = tenant_and_db(request)
        return report(db, gname)

    @app.get("/v1/stats")
    def stats(request: Request):
        tenant, gname = tenant_and_db(request)
        from ...engine.revoke import report as reporting
        out = reporting(db, gname)
        return out
