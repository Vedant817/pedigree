"""Authored synthetic demo fixtures, seeded without deleting or resetting data."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .config import default_integrity, graph_name, validate_tenant
from .db import queries as Q
from .db.schema import check_invariants, ensure_schema
from .engine.ingest import record_action, record_source, remember, sha256_text
from .errors import Conflict


def scenarios_dir() -> Path:
    """Locate demo fixtures for checkouts, editable installs and the container image."""
    override = os.environ.get("PEDIGREE_SCENARIOS_DIR")
    if override:
        return Path(override)
    candidates = [Path.cwd() / "demo" / "scenarios",
                  Path(__file__).resolve().parents[2] / "demo" / "scenarios"]
    for candidate in candidates:
        if candidate.is_dir() and any(candidate.glob("S*.json")):
            return candidate
    return candidates[-1]


def load_scenarios(path: Path | None = None) -> list[dict]:
    path = path or scenarios_dir()
    return [json.loads(file.read_text(encoding="utf-8")) for file in sorted(path.glob("S*.json"))]


def _preflight_existing(db, gname: str, tenant: str, nodes: list[dict]) -> set[str]:
    """Reject collisions across the entire fixture before creating any node or edge.

    Status, taint pointers, timestamps, and support authority are mutable; identity
    fields, source integrity, memory content hashes, and derivation parents are not.
    No marker is required, so already-seeded local demo graphs remain compatible.
    """
    ids = [node["id"] for node in nodes]
    rows = db.ro_query(gname, Q.Q_DEMO_IDENTITIES, {"ids": ids}, op="demo.preflight").result_set or []
    existing = {row[0]: (set(row[1]), dict(row[2])) for row in rows}
    parents: dict[str, set[str]] = {}
    for child, parent in db.ro_query(gname, Q.Q_PARENTS_OF, {"ids": ids}, op="demo.parents").result_set or []:
        parents.setdefault(child, set()).add(parent)
    for node in nodes:
        nid = node["id"]
        if nid not in existing:
            continue
        labels, actual = existing[nid]
        expected = {"id": nid, "tenant": tenant, "conf": list(node.get("conf", []))}
        kind = node["type"]
        if kind == "source":
            expected.update({"kind": node["kind"], "uri": node.get("uri"), "title": node.get("title"),
                             "integrity": node.get("integrity", default_integrity(node["kind"]))})
        elif kind == "memory":
            expected.update({"mkind": node.get("mkind", "fact"),
                             "content_hash": sha256_text(node.get("text", ""))})
            if actual.get("text", "") not in {"", node.get("text", "")}:
                raise Conflict("demo fixture id collides with existing content")
        elif kind == "action":
            expected.update({field: node.get(field) for field in ("tool", "summary", "effect", "risk")})
            expected["artifacts"] = node.get("artifacts", [])
        else:
            raise ValueError("unknown synthetic fixture node type")
        expected_parents = set(node.get("derived_from", node.get("relied_on", [])))
        if (labels != {"Node", kind.capitalize()}
                or any(actual.get(key) != value for key, value in expected.items())
                or parents.get(nid, set()) != expected_parents):
            raise Conflict("demo fixture id collides with existing content or lineage")
    return set(existing)


def seed_scenarios(db, tenant: str = "demo") -> dict:
    validate_tenant(tenant)
    gname = graph_name(tenant)
    scenarios = load_scenarios()
    if not scenarios:
        raise ValueError("demo scenario files are missing")
    nodes = [node for scenario in scenarios for node in scenario["nodes"]]
    # On an existing graph even schema DDL waits until collision checks complete.
    existing = _preflight_existing(db, gname, tenant, nodes) if gname in db.list_graphs() else set()
    ensure_schema(db, gname)
    created = 0
    for node in nodes:
        if node["id"] in existing:
            continue
        fields = {key: value for key, value in node.items() if key != "type"}
        kind = node["type"]
        if kind == "source":
            record_source(db, gname, tenant, **fields)
        elif kind == "memory":
            remember(db, gname, tenant, **fields)
        elif kind == "action":
            record_action(db, gname, tenant, **fields)
        else:
            raise ValueError("unknown synthetic fixture node type")
        created += 1
    # Repair missing support after a partial seed, never replace existing authority.
    for scenario in scenarios:
        for support in scenario.get("corroborations", []):
            db.query(gname, Q.Q_DEMO_ADD_SUPPORT, support, op="demo.support")
    violations = check_invariants(db, gname, expected_tenant=tenant)
    if violations:
        raise Conflict("demo graph invariants failed")
    return {"tenant": tenant, "synthetic": True, "scenarios": [s["id"] for s in scenarios],
            "created": created, "existing": len(existing), "invariants": "pass"}
