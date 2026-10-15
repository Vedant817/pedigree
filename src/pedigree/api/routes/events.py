from __future__ import annotations

from fastapi import FastAPI, Request

from ...adapters import normalize_events
from ...config import LIMITS
from ...db.schema import check_invariants
from ...engine.ingest import artifact_lookup as lookup_fn
from ...engine.ingest import ensure_session, record_action, record_source, remember, session_read
from ...errors import TooLarge
from .. import auth
from ..schemas import EventsPayload


def register(app: FastAPI, db, registry, settings) -> None:
    @app.post("/v1/events")
    def ingest_events(payload: EventsPayload, request: Request):
        auth.authenticate(request)
        tenant = request.state.tenant_id
        gname = request.state.graph_name
        if len(payload.events) > LIMITS["events_per_request"]:
            raise TooLarge(
                "too many events in one request",
                detail={"limit": LIMITS["events_per_request"], "got": len(payload.events)},
            )
        spec_list = normalize_events(payload.runtime, {"session_id": payload.session_id, "events": payload.events})
        created: list[str] = []
        for spec in spec_list:
            op = spec.get("op")
            sid = spec.get("session_id")
            if op == "session":
                ensure_session(db, gname, tenant, sid, runtime=payload.runtime or spec.get("runtime", "other"))
            elif op == "session_read":
                session_read(db, gname, sid, spec.get("node_id"))
            elif op == "source":
                res = record_source(
                    db,
                    gname,
                    tenant,
                    kind=spec.get("kind", "web"),
                    uri=spec.get("uri"),
                    title=spec.get("title"),
                    integrity=spec.get("integrity"),
                    conf=spec.get("conf"),
                    id=spec.get("id"),
                )
                created.append(res.id)
            elif op == "memory":
                res = remember(
                    db,
                    gname,
                    tenant,
                    text=spec.get("text", ""),
                    derived_from=spec.get("derived_from") or [],
                    corroborated_by=spec.get("corroborated_by") or [],
                    artifact=spec.get("artifact"),
                    artifact_key=spec.get("artifact_key"),
                    id=spec.get("id"),
                )
                created.append(res.id)
            elif op == "action":
                res = record_action(
                    db,
                    gname,
                    tenant,
                    tool=spec.get("tool", "unknown"),
                    summary=spec.get("summary", ""),
                    relied_on=spec.get("relied_on") or [],
                    decision=spec.get("decision"),
                    effect=spec.get("effect"),
                    risk=spec.get("risk"),
                    artifacts=spec.get("artifacts") or [],
                    artifact_key=spec.get("artifact_key"),
                    session_id=sid,
                    id=spec.get("id"),
                )
                created.append(res.id)
            else:
                continue
        return {"created": created}

    @app.get("/v1/artifacts/lookup")
    def artifact_lookup(key: str, request: Request):
        auth.authenticate(request)
        gname = request.state.graph_name
        result = lookup_fn(db, gname, key)
        first, node_id = result if result else (None, None)
        if first is not None:
            return {"found": True, "kind": first, "node_id": node_id}
        return {"found": False}

    @app.get("/v1/invariants")
    def invariants(request: Request):
        auth.authenticate(request)
        gname = request.state.graph_name
        return {"violations": check_invariants(db, gname, request.state.tenant_id)}
