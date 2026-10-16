"""Ingest engine: record_source / remember / record_action / corroborate (+ sessions).

Rules (docs/01 section 6.1):
- parents are validated BEFORE writing: `MATCH` silently drops missing parents (GOTCHAS #16);
- each create is ONE atomic query that also inherits `low_integrity`, `conf_eff` and the
  born-quarantined status from the parents;
- a child of a revoked/tainted/quarantined parent is born `quarantined` (race-safe barrier);
- edges carry `rel` (derive|rely) and `via` (cite|session_read|agent_reported|hook) so
  agent-reported lineage is always distinguishable from hook-captured lineage.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass, field
from types import SimpleNamespace

from ..config import (
    LIMITS,
    MEMORY_KINDS,
    SOURCE_KINDS,
    Settings,
    default_integrity,
    get_settings,
    validate_artifact,
    validate_id,
    validate_tenant,
)
from ..db import queries as Q
from ..db.client import Db, Trace, chunks
from ..errors import Conflict, InvalidArgument, NotFoundInGraph, TooLarge

VIA_VALUES = ("cite", "session_read", "agent_reported", "hook")


@dataclass
class IngestResult:
    id: str
    status: str
    low_integrity: bool
    conf_eff: list[str]
    n_parents: int
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "low_integrity": self.low_integrity,
            "conf_eff": self.conf_eff,
            "n_parents": self.n_parents,
            "warnings": self.warnings,
        }


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def derived_source_id(tenant: str, uri: str) -> str:
    """Stable node id for a hash-less capture (ADR-008): the artifact uri names the Source.
    Enforced by the Node(id) unique constraint, so concurrent identical captures converge
    (a MERGE keyed on a NULL content_hash does not - NULLs are exempt from the pair
    constraint, measured with 10 concurrent writers)."""
    return "src_" + hashlib.sha256(f"{tenant}|{uri}".encode()).hexdigest()[:16]


def _dedupe(seq) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _validate_ids(ids, cap: int, field_name: str) -> list[str]:
    if len(ids) > cap:
        raise TooLarge(f"too many ids in {field_name}", detail={"limit": cap, "got": len(ids)})
    return [validate_id(i) for i in ids]


def _validate_conf(conf) -> list[str]:
    conf = _dedupe([str(c) for c in conf])
    if len(conf) > LIMITS["conf_tags"]:
        raise TooLarge("too many confidentiality tags", detail={"limit": LIMITS["conf_tags"]})
    for c in conf:
        if not c or len(c) > 32:
            raise InvalidArgument("invalid confidentiality tag", detail={"tag": c[:32]})
    return conf


def _str_prop(value: str | None, limit: int, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise InvalidArgument(f"invalid {name}", detail={"limit": limit})
    return value


def require_nodes(db: Db, gname: str, ids: list[str], trace: Trace | None, *, op: str = "ingest.find") -> None:
    """Raise NotFoundInGraph listing every id that is not in the graph."""
    if not ids:
        return
    res = db.ro_query(gname, Q.Q_FIND_IDS, {"ids": ids}, op=op, trace=trace)
    found = {row[0] for row in res.result_set or []}
    missing = [i for i in ids if i not in found]
    if missing:
        raise NotFoundInGraph("unknown ids", detail={"missing": missing[:16], "n_missing": len(missing)})


def record_source(
    db: Db,
    gname: str,
    tenant: str,
    *,
    kind: str,
    uri: str | None = None,
    title: str | None = None,
    content_hash: str | None = None,
    integrity: str | None = None,
    conf=None,
    id: str | None = None,
    now: int | None = None,
    trace: Trace | None = None,
) -> IngestResult:
    if kind not in SOURCE_KINDS:
        raise InvalidArgument("unknown source kind", detail={"kind": str(kind)[:32]})
    tenant = validate_tenant(tenant)
    integrity = integrity or default_integrity(kind)
    if integrity not in ("trusted", "untrusted"):
        raise InvalidArgument("invalid integrity", detail={"integrity": str(integrity)[:16]})
    conf = _validate_conf(conf or [])
    node_id = validate_id(id) if id else new_id("src")
    props: dict = {
        "id": node_id,
        "tenant": tenant,
        "status": "ok",
        "kind": kind,
        "integrity": integrity,
        "low_integrity": integrity == "untrusted",
        "conf": conf,
        "conf_eff": conf,
    }
    uri = _str_prop(uri, LIMITS["uri_len"], "uri")
    title = _str_prop(title, LIMITS["title_len"], "title")
    if uri:
        props["uri"] = uri
    if title:
        props["title"] = title
    if content_hash:
        if len(content_hash) != 64 or any(c not in "0123456789abcdef" for c in content_hash.lower()):
            raise InvalidArgument("content_hash must be 64 hex chars")
        props["content_hash"] = content_hash.lower()

    try:
        # Derived identity: the artifact (uri [+ content_hash]) names the node, so repeated
        # reads converge instead of minting a second Source (consult 007 / ADR-008). A
        # caller-supplied id names the node at creation only; it never forks the same
        # content into two nodes.
        if uri and content_hash:
            try:
                res = db.query(gname, Q.Q_SOURCE_MERGE_HASHED,
                               {"tenant": tenant, "uri": uri, "hash": content_hash.lower(),
                                "props": props, "now": now or now_ms()},
                               op="ingest.source", trace=trace)
            except Conflict:
                # a concurrent writer created the same artifact first: read it back, so the
                # caller converges on that node instead of seeing an error
                back = db.ro_query(gname, Q.Q_SOURCE_BY_ARTIFACT,
                                   {"tenant": tenant, "uri": uri, "hash": content_hash.lower()},
                                   op="ingest.source_readback", trace=trace).result_set or []
                if not back:
                    raise
                res = SimpleNamespace(result_set=[back[0]])
        elif uri and not id:
            # hash-less capture: identity is the derived id, enforced by Node(id)
            props["id"] = derived_source_id(tenant, uri)
            res = db.query(gname, Q.Q_SOURCE_MERGE_URI,
                           {"derived": props["id"], "props": props, "now": now or now_ms()},
                           op="ingest.source", trace=trace)
        else:
            res = db.query(
                gname, Q.Q_CREATE_SOURCE, {"props": props, "now": now or now_ms()}, op="ingest.source", trace=trace
            )
    except Conflict as exc:
        # The caller's id already belongs to different content - an identity conflict,
        # never a silent duplicate.
        raise Conflict("source id already exists", detail={"id": node_id}) from exc
    row = res.result_set[0]
    warnings: list[str] = []
    if integrity == "untrusted":
        warnings.append("untrusted_source")
    return IngestResult(row[0], row[1], bool(row[2]), list(row[3] or []), 0, warnings)


def remember(
    db: Db,
    gname: str,
    tenant: str,
    *,
    text: str = "",
    mkind: str = "fact",
    derived_from=(),
    corroborated_by=(),
    conf=None,
    artifact: str | None = None,
    artifact_key: str | None = None,
    content_hash: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
    id: str | None = None,
    via: str = "cite",
    settings: Settings | None = None,
    now: int | None = None,
    trace: Trace | None = None,
) -> IngestResult:
    if mkind not in MEMORY_KINDS:
        raise InvalidArgument("unknown memory kind", detail={"mkind": str(mkind)[:32]})
    tenant = validate_tenant(tenant)
    if not isinstance(text, str) or len(text) > LIMITS["text_len"]:
        raise TooLarge("memory text too long", detail={"limit": LIMITS["text_len"]})
    if via not in VIA_VALUES:
        raise InvalidArgument("invalid via")
    parents = _validate_ids(_dedupe(derived_from), LIMITS["derived_from"], "derived_from")
    corr = _validate_ids(_dedupe(corroborated_by), LIMITS["corroborated_by"], "corroborated_by")
    conf = _validate_conf(conf or [])
    st = settings or get_settings()
    keep_text = st.pedigree_store_text
    h = content_hash or (sha256_text(text) if text else None)

    node_id = validate_id(id) if id else new_id("mem")
    props: dict = {
        "id": node_id,
        "tenant": tenant,
        "mkind": mkind,
        "text": text if keep_text else "",
        "conf": conf,
    }
    if h:
        props["content_hash"] = h
    if artifact:
        props["artifact"] = _str_prop(artifact, LIMITS["artifact_str_len"], "artifact")
    if artifact_key:
        props["artifact_key"] = _str_prop(artifact_key, LIMITS["artifact_str_len"] * 2, "artifact_key")
    if agent_id:
        props["agent_id"] = _str_prop(agent_id, 128, "agent_id")
    if session_id:
        props["session_id"] = _str_prop(session_id, 128, "session_id")

    warnings: list[str] = []
    if not keep_text and text:
        warnings.append("text_not_stored")

    # P-031 (B4): derived_from parents may only be existing Source/Memory/Action nodes.
    for _p in parents:
        _exists, _labels = node_exists(db, gname, _p, trace)
        if not _exists:
            continue  # `require_nodes` below raises NotFoundInGraph
        if not (set(_labels) & {"Source", "Memory", "Action"}):
            raise InvalidArgument(
                "parent must be a Source, Memory, or Action node",
                detail={"parent": _p, "labels": sorted(_labels or [])},
            )

    require_nodes(db, gname, parents, trace)
    with_trace = trace
    if parents:
        res = db.query(
            gname,
            Q.q_create_with_parents("Memory"),
            {"props": props, "now": now or now_ms(), "parents": parents, "rel": "derive", "via": via},
            op="ingest.memory",
            trace=with_trace,
        )
    else:
        props.update({"status": "ok", "unanchored": True, "low_integrity": True, "conf_eff": conf})
        res = db.query(
            gname, Q.q_create_orphan("Memory"), {"props": props, "now": now or now_ms()},
            op="ingest.memory_orphan", trace=with_trace,
        )
        warnings.append("unanchored")

    row = res.result_set[0]
    n_parents = int(row[4])
    if parents and n_parents != len(parents):
        # A parent was dropped between validation and write: refuse to keep an incomplete edge set.
        raise Conflict("parent disappeared during write", detail={"expected": len(parents), "got": n_parents})

    result = IngestResult(row[0], row[1], bool(row[2]), list(row[3] or []), n_parents, warnings)
    if result.low_integrity and "untrusted_inherited" not in warnings:
        warnings.append("low_integrity")

    if corr:
        require_nodes(db, gname, corr, trace, op="ingest.find")
        for sid in corr:
            corroborate(db, gname, result.id, sid, by="agent", trace=trace)
    if session_id:
        session_read(db, gname, session_id, result.id, trace=trace)
    return result


def record_action(
    db: Db,
    gname: str,
    tenant: str,
    *,
    tool: str,
    summary: str = "",
    relied_on=(),
    effect: str | None = None,
    risk: str | None = None,
    artifacts=(),
    artifact_key: str | None = None,
    session_id: str | None = None,
    agent_id: str | None = None,
    decision: str | None = None,
    id: str | None = None,
    via: str = "cite",
    now: int | None = None,
    trace: Trace | None = None,
) -> IngestResult:
    if not isinstance(tool, str) or not tool or len(tool) > 128:
        raise InvalidArgument("invalid tool name")
    tenant = validate_tenant(tenant)
    if len(summary) > LIMITS["summary_len"]:
        raise TooLarge("summary too long", detail={"limit": LIMITS["summary_len"]})
    if effect is not None and effect not in ("reversible", "irreversible", "unknown"):
        raise InvalidArgument("invalid effect")
    if risk is not None and risk not in ("low", "medium", "high"):
        raise InvalidArgument("invalid risk")
    if via not in VIA_VALUES:
        raise InvalidArgument("invalid via")
    parents = _validate_ids(_dedupe(relied_on), LIMITS["relied_on"], "relied_on")
    arts = (
        [validate_artifact(a) for a in _dedupe(artifacts)]
        if artifacts
        else []
    )
    if len(arts) > LIMITS["artifacts"]:
        raise TooLarge("too many artifacts", detail={"limit": LIMITS["artifacts"]})

    node_id = validate_id(id) if id else new_id("act")
    props: dict = {"id": node_id, "tenant": tenant, "tool": tool, "summary": summary, "conf": []}
    if effect:
        props["effect"] = effect
    if risk:
        props["risk"] = risk
    if arts:
        props["artifacts"] = arts
    if artifact_key:
        props["artifact_key"] = _str_prop(artifact_key, LIMITS["artifact_str_len"] * 2, "artifact_key")
    if session_id:
        props["session_id"] = _str_prop(session_id, 128, "session_id")
    if agent_id:
        props["agent_id"] = _str_prop(agent_id, 128, "agent_id")
    if decision:
        props["decision"] = _str_prop(decision, 32, "decision")

    warnings: list[str] = []
    require_nodes(db, gname, parents, trace)
    if parents:
        res = db.query(
            gname,
            Q.q_create_with_parents("Action"),
            {"props": props, "now": now or now_ms(), "parents": parents, "rel": "rely", "via": via},
            op="ingest.action",
            trace=trace,
        )
    else:
        props.update({"status": "ok", "unanchored": True, "low_integrity": True, "conf_eff": []})
        res = db.query(
            gname, Q.q_create_orphan("Action"), {"props": props, "now": now or now_ms()},
            op="ingest.action_orphan", trace=trace,
        )
        warnings.append("unanchored")
    row = res.result_set[0]
    n_parents = int(row[4])
    if parents and n_parents != len(parents):
        raise Conflict("parent disappeared during write", detail={"expected": len(parents), "got": n_parents})
    result = IngestResult(row[0], row[1], bool(row[2]), list(row[3] or []), n_parents, warnings)
    if session_id:
        session_read(db, gname, session_id, result.id, trace=trace)
    return result


def corroborate(db: Db, gname: str, memory_id: str, source_id: str, *, by: str = "agent", trace: Trace | None = None) -> None:
    if by not in ("agent", "human", "scanner"):
        raise InvalidArgument("invalid corroboration author", detail={"by": str(by)[:16]})
    res = db.query(
        gname, Q.Q_CORROBORATE, {"m": memory_id, "s": source_id, "by": by},
        op="ingest.corroborate", trace=trace,
    )
    if not res.result_set:
        raise NotFoundInGraph("memory or source not found", detail={"memory": memory_id, "source": source_id})


# --- sessions ---------------------------------------------------------------
def ensure_session(
    db: Db, gname: str, tenant: str, session_id: str, *, runtime: str = "other",
    agent_id: str | None = None, now: int | None = None, trace: Trace | None = None,
) -> str:
    session_id = validate_id(session_id)
    res = db.ro_query(gname, Q.Q_GET_SESSION, {"id": session_id}, op="ingest.session_get", trace=trace)
    if res.result_set:
        return session_id
    db.query(
        gname, Q.Q_CREATE_SESSION,
        {"id": session_id, "tenant": tenant, "runtime": runtime, "agent": agent_id, "now": now or now_ms()},
        op="ingest.session", trace=trace,
    )
    return session_id


def session_read(db: Db, gname: str, session_id: str, node_id: str, *, now: int | None = None, trace: Trace | None = None) -> None:
    res = db.query(
        gname, Q.Q_SESSION_READ, {"sess": session_id, "n": node_id, "now": now or now_ms()},
        op="ingest.read", trace=trace,
    )
    if not res.result_set:
        raise NotFoundInGraph("session or node not found", detail={"session": session_id, "node": node_id})


def read_window(db: Db, gname: str, session_id: str, k: int = 50, trace: Trace | None = None) -> list[str]:
    res = db.ro_query(
        gname, Q.Q_READ_WINDOW, {"sess": session_id, "k": int(k)}, op="ingest.window", trace=trace
    )
    return [row[0] for row in res.result_set or []]


def artifact_lookup(db: Db, gname: str, key: str, trace: Trace | None = None) -> tuple[str, str] | None:
    """Look up `path@sha256` on Memory first, then on Action (cross-session link)."""
    for cypher, label in ((Q.Q_ARTIFACT_LOOKUP_MEMORY, "Memory"), (Q.Q_ARTIFACT_LOOKUP_ACTION, "Action")):
        res = db.ro_query(gname, cypher, {"k": key}, op="ingest.artifact", trace=trace)
        if res.result_set:
            return label, res.result_set[0][0]
    return None


def node_exists(db: Db, gname: str, node_id: str, trace: Trace | None = None) -> tuple[bool, list[str]]:
    res = db.ro_query(gname, Q.Q_NODE_BY_ID, {"id": node_id}, op="ingest.node", trace=trace)
    if not res.result_set:
        return False, []
    return True, list(res.result_set[0][1] or [])


def get_node_statuses(db: Db, gname: str, ids, trace: Trace | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    for ch in chunks(list(ids)):
        res = db.ro_query(gname, Q.Q_NODE_STATUSES, {"ids": ch}, op="ingest.statuses", trace=trace)
        for nid, st in res.result_set or []:
            out[nid] = st
    return out
