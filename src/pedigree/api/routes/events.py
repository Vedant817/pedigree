from __future__ import annotations

from fastapi import FastAPI, Request

from ...adapters import normalize_events
from ...config import LIMITS
from ...db.schema import check_invariants
from ...engine.gate import classify_action, load_policy
from ...engine.ingest import artifact_lookup as lookup_fn
from ...engine.ingest import (
    ensure_session,
    read_window,
    record_action,
    record_source,
    remember,
    session_read,
)
from ...engine.quota import QuotaPolicy, admission, preflight
from ...errors import InvalidArgument, TooLarge
from .. import auth
from ..routes.engine import operator_authorized
from ..schemas import EventsPayload


def register(app: FastAPI, db, registry, settings) -> None:
    @app.post("/v1/events")
    def ingest_events(payload: EventsPayload, request: Request):
        auth.authenticate(request)
        db = request.state.db
        tenant = request.state.tenant_id
        gname = request.state.graph_name
        if len(payload.events) > LIMITS["events_per_request"]:
            raise TooLarge(
                "too many events in one request",
                detail={"limit": LIMITS["events_per_request"], "got": len(payload.events)},
            )
        operator = operator_authorized(request, settings)
        # Authorize every trust-bearing assertion before the first admission/write.
        for raw in payload.events:
            if isinstance(raw, dict):
                if raw.get("by") in ("human", "scanner") and not operator:
                    auth.require_operator(request)
                auth.authorize_source(request.state.principal, raw.get("source_kind") or raw.get("kind"), raw.get("integrity"))
        spec_list = normalize_events(payload.runtime, {"session_id": payload.session_id, "events": payload.events})
        for spec in spec_list:
            if spec.get("op") == "source":
                auth.authorize_source(request.state.principal, spec.get("kind"), spec.get("integrity"))
                if spec.get("artifact_key") and payload.delivery_id is None:
                    raise InvalidArgument("deferred artifact lookup requires delivery_id")
        auth.admit(request, "write")
        if payload.delivery_id is not None:
            from ...engine.capture import deliver
            return deliver(db, gname, tenant, payload, spec_list, settings, registry.get_record(tenant).node_cap)
        created: list[str] = []
        # In-batch alias map: a capture id names a node, but identity is derived from the
        # artifact (ADR-008), so later events in the same batch that reference the id are
        # rewritten to the canonical node id.
        aliases: dict[str, str] = {}

        def resolve(value):
            return aliases.get(value, value) if isinstance(value, str) else value

        with admission(db, gname, QuotaPolicy(tenant, registry.get_record(tenant).node_cap)) as locked_db:
            preflight(locked_db, gname, tenant, spec_list)
            for spec in spec_list:
                op = spec.get("op")
                sid = spec.get("session_id")
                if op == "session":
                    ensure_session(locked_db, gname, tenant, sid, runtime=payload.runtime or spec.get("runtime", "other"))
                elif op == "session_read":
                    session_read(locked_db, gname, sid, resolve(spec.get("node_id")))
                elif op == "source":
                    # Agent context captures cannot create trust; rejected claims were
                    # checked for the entire batch before admission.
                    res = record_source(
                        locked_db,
                        gname,
                        tenant,
                        kind=spec.get("kind", "web"),
                        uri=spec.get("uri"),
                        title=spec.get("title"),
                        integrity=spec.get("integrity") if operator else "untrusted",
                        content_hash=spec.get("content_hash"),
                        conf=spec.get("conf"),
                        id=spec.get("id"),
                    )
                    if spec.get("id"):
                        aliases[spec["id"]] = res.id
                    created.append(res.id)
                elif op == "memory":
                    res = remember(
                        locked_db,
                        gname,
                        tenant,
                        text=spec.get("text", ""),
                        derived_from=[resolve(x) for x in (spec.get("derived_from") or [])],
                        corroborated_by=[resolve(x) for x in (spec.get("corroborated_by") or [])],
                        artifact=spec.get("artifact"),
                        artifact_key=spec.get("artifact_key"),
                        id=spec.get("id"),
                        session_id=sid,
                        via="hook" if payload.runtime in {"claude-code", "opencode"} else "agent_reported",
                    )
                    created.append(res.id)
                elif op == "action":
                    parents = [resolve(x) for x in (spec.get("relied_on") or [])] or (
                        read_window(locked_db, gname, sid, settings.pedigree_read_window) if sid else [])
                    effect, risk = classify_action(load_policy(settings.pedigree_policy_file),
                                                    spec.get("tool", "unknown"), spec.get("summary", ""),
                                                    effect=spec.get("effect"), risk=spec.get("risk"))
                    res = record_action(
                        locked_db,
                        gname,
                        tenant,
                        tool=spec.get("tool", "unknown"),
                        summary=spec.get("summary", ""),
                        relied_on=parents,
                        decision=spec.get("decision"),
                        effect=effect,
                        risk=risk,
                        artifacts=spec.get("artifacts") or [],
                        artifact_key=spec.get("artifact_key"),
                        session_id=sid,
                        id=spec.get("id"),
                        via="hook" if payload.runtime in {"claude-code", "opencode"} else "agent_reported",
                    )
                    created.append(res.id)
                else:
                    continue
        return {"created": created}

    @app.get("/v1/artifacts/lookup")
    def artifact_lookup(key: str, request: Request):
        auth.authenticate(request)
        db = request.state.db
        gname = request.state.graph_name
        auth.admit(request, "read")
        result = lookup_fn(db, gname, key)
        first, node_id = result if result else (None, None)
        if first is not None:
            return {"found": True, "kind": first, "node_id": node_id}
        return {"found": False}

    @app.get("/v1/invariants")
    def invariants(request: Request):
        auth.authenticate(request)
        db = request.state.db
        gname = request.state.graph_name
        auth.admit(request, "read")
        return {"violations": check_invariants(db, gname, request.state.tenant_id)}
