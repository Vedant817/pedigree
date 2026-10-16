from __future__ import annotations

import hmac
import time

from fastapi import FastAPI, Request

from ...config import graph_name
from ...db.schema import ensure_schema
from ...engine.audit import audit_sources
from ...engine.blame import blame as run_blame
from ...engine.blame import impact as run_impact
from ...engine.ingest import corroborate, ensure_session, record_action, record_source, remember, session_read
from ...engine.quota import QuotaPolicy, admission
from ...engine.revoke import reinstate, report, revoke
from ...engine.whatif import whatif
from ...errors import InvalidArgument, PedigreeError
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
    WhatIfRequest,
)

#: Source kinds whose default integrity is trusted. An agent token cannot mint them: the
#: capture channel records everything an agent reports as untrusted, and the direct channel
#: only accepts them with the operator credential (consult 007 / ADR-008).
AGENT_SAFE_KINDS = frozenset({"web", "tool_output", "mcp_tool_desc", "other"})


def operator_authorized(request: Request, settings) -> bool:
    """True only when the deployment's operator credential is configured and matches."""
    expected = (getattr(settings, "pedigree_admin_token", "") or "").strip()
    if not expected:
        return False
    presented = request.headers.get("X-Admin-Token", "").strip()
    return bool(presented) and hmac.compare_digest(presented, expected)


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

    @app.post("/v1/sources")
    def create_source(payload: SourceCreate, request: Request):
        tenant, gname = tenant_and_db(request)
        gate(request, tenant)
        operator = operator_authorized(request, settings)
        if payload.kind not in AGENT_SAFE_KINDS and not operator:
            raise InvalidArgument(
                "this source kind needs the operator credential",
                detail={"kind": payload.kind, "header": "X-Admin-Token"},
            )
        # An agent token never asserts integrity; without the operator credential every
        # recorded source is untrusted whatever the body claims (ADR-008).
        integrity = payload.integrity if (operator and payload.integrity) else (
            None if operator else "untrusted")
        res = record_source(
            db, gname, tenant, quota=QuotaPolicy(tenant, registry.get_record(tenant).node_cap),
            kind=payload.kind,
            uri=payload.uri,
            title=payload.title,
            content_hash=payload.content_hash,
            integrity=integrity,
            conf=payload.conf,
            id=payload.id,
        )
        return {"id": res.id, "status": res.status, "low_integrity": res.low_integrity,
                "conf_eff": res.conf_eff, "warnings": res.warnings}

    @app.post("/v1/memories")
    def create_memory(payload: MemoryCreate, request: Request):
        tenant, gname = tenant_and_db(request)
        gate(request, tenant)
        res = remember(
            db, gname, tenant, quota=QuotaPolicy(tenant, registry.get_record(tenant).node_cap),
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
        res = record_action(
            db, gname, tenant, quota=QuotaPolicy(tenant, registry.get_record(tenant).node_cap),
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
        if payload.by in ("human", "scanner") and not operator_authorized(request, settings):
            raise PedigreeError("trusted attestation needs the operator credential",
                                code="forbidden", detail={"header": "X-Admin-Token"})
        corroborate(db, gname, payload.memory_id, payload.source_id, by=payload.by, quota=QuotaPolicy(tenant, registry.get_record(tenant).node_cap))
        return {"ok": True, "by": payload.by}

    @app.post("/v1/sessions")
    def ensure(payload: EnsureSessionRequest, request: Request):
        tenant, gname = tenant_and_db(request)
        sid = ensure_session(db, gname, tenant, payload.session_id, runtime=payload.runtime, agent_id=payload.agent_id, quota=QuotaPolicy(tenant, registry.get_record(tenant).node_cap))
        return {"session_id": sid}

    @app.post("/v1/sessions/read")
    def sread(payload: SessionReadRequest, request: Request):
        tenant, gname = tenant_and_db(request)
        with admission(db, gname, QuotaPolicy(tenant, registry.get_record(tenant).node_cap)) as locked_db:
            if payload.ensure == "yes":
                ensure_session(locked_db, gname, tenant, payload.session_id, runtime=payload.runtime)
            session_read(locked_db, gname, payload.session_id, payload.node_id)
        return {"ok": True}

    @app.post("/v1/revoke")
    def do_revoke(payload: RevokeRequest, request: Request):
        tenant, gname = tenant_and_db(request)
        gate(request, tenant, "revoke")
        gate(request, tenant)  # establish sane consistent state
        out = revoke(db, gname, tenant, root_id=payload.root_id, reason=payload.reason,
                    dry_run=payload.dry_run, kind=payload.kind, quota=QuotaPolicy(tenant, registry.get_record(tenant).node_cap))
        return out

    @app.post("/v1/whatif")
    def do_whatif(payload: WhatIfRequest, request: Request):
        tenant, gname = tenant_and_db(request)
        gate(request, tenant)
        return whatif(db, gname, tenant, payload.roots, reason=payload.reason)

    @app.post("/v1/reinstate")
    def do_reinstate(payload: ReinstateRequest, request: Request):
        tenant, gname = tenant_and_db(request)
        gate(request, tenant)
        out = reinstate(db, gname, tenant, root_id=payload.root_id, dry_run=payload.dry_run, quota=QuotaPolicy(tenant, registry.get_record(tenant).node_cap))
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

    @app.get("/v1/audit/sources")
    def audit(request: Request, limit: int = 50):
        tenant, gname = tenant_and_db(request)
        return audit_sources(db, gname, limit=limit)

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
