"""Bounded real-DB CI sentinel; full 20k/60k acceptance remains check-perf."""

import time

import pytest

from pedigree.db.schema import check_invariants
from pedigree.engine.gate import check_action
from pedigree.engine.revoke import revoke

pytestmark = pytest.mark.perf


def test_bounded_cascade_and_gate(fresh_graph):
    db, tenant, graph = fresh_graph
    db.query(graph, """
        UNWIND range(0, 999) AS i
        CREATE (m:Node:Memory {id: 'lite' + toString(i), tenant: $tenant,
            kind: 'fact', status: 'ok', text: 'CI synthetic memory',
            low_integrity: false, conf: [], conf_eff: [], created_at: 0})
        RETURN count(m)
        """, {"tenant": tenant})
    db.query(graph, """
        UNWIND range(1, 999) AS i
        MATCH (root:Node {id: 'lite0'}), (child:Node {id: 'lite' + toString(i)})
        CREATE (root)-[:FEEDS]->(child), (child)-[:DERIVED_FROM]->(root)
        RETURN count(child)
        """)
    start = time.perf_counter()
    result = revoke(db, graph, tenant, root_id="lite0", reason="bounded CI perf sentinel")
    assert result["counts"]["tainted"] >= 999
    assert result["state"] == "done"
    assert time.perf_counter() - start < 10
    start = time.perf_counter()
    decision = check_action(db, graph, {"tool": "shell", "summary": "CI synthetic gate", "risk": "high"},
                            relied_on=["lite1"])
    assert decision["decision"] == "block"
    assert time.perf_counter() - start < 1
    assert check_invariants(db, graph, expected_tenant=tenant) == []
