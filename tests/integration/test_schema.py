"""AT0.3 / AT0.5 - schema idempotency, the unique constraint, and invariant detection."""

from __future__ import annotations

import pytest

from pedigree.db.queries import Q_INDEXES
from pedigree.db.schema import check_invariants, ensure_schema
from pedigree.engine.ingest import record_source, remember
from pedigree.errors import Conflict

# Verified against FalkorDB v4.22.1: CREATE INDEX statements targeting the same label are
# merged into ONE row (e.g. Revocation covers both root_id and state), so we assert
# property coverage, not a raw row count.
REQUIRED_INDEX_PAIRS = {
    ("Node", "id"),
    ("Memory", "artifact_key"),
    ("Action", "artifact_key"),
    ("Revocation", "root_id"),
    ("Revocation", "state"),
}


def _covered_pairs(db, gname) -> set[tuple[str, str]]:
    rows = db.ro_query(gname, Q_INDEXES).result_set or []
    pairs: set[tuple[str, str]] = set()
    for r in rows:
        label = r[0].decode() if isinstance(r[0], bytes) else r[0]
        for prop in r[1]:
            p = prop.decode() if isinstance(prop, bytes) else prop
            pairs.add((label, p))
    return pairs


def test_ensure_schema_is_idempotent(fresh_graph):
    db, tenant, gname = fresh_graph
    first = ensure_schema(db, gname)
    second = ensure_schema(db, gname)
    assert REQUIRED_INDEX_PAIRS <= _covered_pairs(db, gname)
    assert second["n_indexes"] == first["n_indexes"]


def test_unique_constraint_rejects_duplicate_ids(fresh_graph):
    db, tenant, gname = fresh_graph
    record_source(db, gname, tenant, kind="web", id="dup1")
    with pytest.raises(Conflict):
        record_source(db, gname, tenant, kind="web", id="dup1")


def test_invariants_pass_on_a_healthy_graph(fresh_graph):
    db, tenant, gname = fresh_graph
    s = record_source(db, gname, tenant, kind="web", id="s1")
    remember(db, gname, tenant, text="hi", derived_from=[s.id], id="m1")
    assert check_invariants(db, gname, expected_tenant=tenant) == []


def test_invariants_detect_unknown_status(fresh_graph):
    db, tenant, gname = fresh_graph
    db.query(
        gname,
        "CREATE (:Node {id:'bad1', tenant:$t, status:'bogus', created_at:1})",
        {"t": tenant},
        op="test.corrupt",
    )
    violations = check_invariants(db, gname)
    assert any("unknown status" in v for v in violations), violations


def test_invariants_detect_broken_mirror(fresh_graph):
    db, tenant, gname = fresh_graph
    s = record_source(db, gname, tenant, kind="web", id="s1")
    remember(db, gname, tenant, text="hi", derived_from=[s.id], id="m1")
    assert check_invariants(db, gname) == []
    db.query(gname, "MATCH ()-[f:FEEDS]->() DELETE f", {}, op="test.corrupt")
    violations = check_invariants(db, gname)
    assert any("mirrored FEEDS" in v for v in violations), violations


def test_invariants_detect_cycle(fresh_graph):
    db, tenant, gname = fresh_graph
    db.query(
        gname,
        "CREATE (:Node:Memory {id:'a', tenant:$t, status:'ok', created_at:1})"
        ", (:Node:Memory {id:'b', tenant:$t, status:'ok', created_at:2})",
        {"t": tenant},
        op="test.corrupt",
    )
    db.query(
        gname,
        "MATCH (a:Node {id:'a'}), (b:Node {id:'b'}) "
        "CREATE (a)-[:DERIVED_FROM {rel:'derive', via:'cite'}]->(b), (a)-[:FEEDS]->(b), "
        "(b)-[:DERIVED_FROM {rel:'derive', via:'cite'}]->(a), (b)-[:FEEDS]->(a)",
        {},
        op="test.corrupt",
    )
    violations = check_invariants(db, gname)
    assert any("cycle" in v for v in violations), violations


def test_invariants_detect_wrong_tenant(fresh_graph):
    db, tenant, gname = fresh_graph
    record_source(db, gname, tenant, kind="web", id="s1")
    violations = check_invariants(db, gname, expected_tenant="othertenant")
    assert any("tenant" in v for v in violations), violations
