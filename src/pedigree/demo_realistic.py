"""Synthetic coding-agent trace for the second demo tenant.

The authored S1/S8 fixtures stay small. This trace is a separate graph: a poisoned
README, a memory that tells the agent to pipe an installer through a shell, and a
force-push that relied on that memory. The rest is deterministic filler so the
map is large enough to walk. Nothing here is a recorded Claude session.

Tenant ids cannot contain a hyphen, so the tenant is ``demorealistic`` rather
than the hyphenated name in the plan.
"""
from __future__ import annotations

import hashlib

from .config import graph_name, validate_tenant
from .db.schema import check_invariants, ensure_schema
from .demo import _preflight_existing
from .engine.ingest import record_action, record_source, remember
from .errors import Conflict

REALISTIC_TENANT = "demorealistic"
POISON_ID = "rf_src_readme"
INSTALL_ID = "rf_mem_install"
PUSH_ID = "rf_act_force_push"
_FILE_COUNT = 100
_MEMORY_COUNT = 150
_PLAIN_ACTIONS = 49


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def realistic_nodes() -> list[dict]:
    """Parents are listed before the nodes that derive from them."""
    nodes: list[dict] = [{
        "type": "source",
        "id": POISON_ID,
        "kind": "web",
        "integrity": "untrusted",
        "uri": "https://example.com/install/README.md",
        "title": "Poisoned installer README",
        "content_hash": _hash("poisoned-readme"),
    }]
    for index in range(_FILE_COUNT):
        nodes.append({
            "type": "source",
            "id": f"rf_src_{index:03d}",
            "kind": "file",
            "integrity": "untrusted",
            "uri": f"file://repo/src/module_{index:03d}.py",
            "title": f"module_{index:03d}.py",
            "content_hash": _hash(f"module-{index}"),
        })
    nodes.append({
        "type": "memory",
        "id": INSTALL_ID,
        "mkind": "procedure",
        "text": "use curl|sh installer",
        "derived_from": [POISON_ID],
    })
    for index in range(_MEMORY_COUNT):
        parent = INSTALL_ID if index % 15 == 0 else f"rf_src_{index % _FILE_COUNT:03d}"
        nodes.append({
            "type": "memory",
            "id": f"rf_mem_{index:03d}",
            "mkind": "fact",
            "text": f"session note {index}",
            "derived_from": [parent],
        })
    nodes.append({
        "type": "action",
        "id": PUSH_ID,
        "tool": "Bash",
        "summary": "git push --force origin main",
        "effect": "irreversible",
        "risk": "high",
        "decision": "block",
        "relied_on": [INSTALL_ID],
    })
    for index in range(_PLAIN_ACTIONS):
        nodes.append({
            "type": "action",
            "id": f"rf_act_{index:03d}",
            "tool": "Bash",
            "summary": f"git status {index}",
            "effect": "reversible",
            "risk": "low",
            "relied_on": [f"rf_mem_{index:03d}"],
        })
    return nodes


def seed_realistic(db, tenant: str = REALISTIC_TENANT) -> dict:
    validate_tenant(tenant)
    gname = graph_name(tenant)
    nodes = realistic_nodes()
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
    violations = check_invariants(db, gname, expected_tenant=tenant)
    if violations:
        raise Conflict("demo graph invariants failed")
    actions = sum(1 for node in nodes if node["type"] == "action")
    return {
        "tenant": tenant,
        "synthetic": True,
        "profile": "realistic",
        "created": created,
        "existing": len(existing),
        "nodes": len(nodes),
        "actions": actions,
        "poison_source": POISON_ID,
        "blocked_action": PUSH_ID,
        "invariants": "pass",
    }
