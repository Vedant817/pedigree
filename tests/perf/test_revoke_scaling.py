"""P-010 perf gates against a REAL FalkorDB (marker: perf - run with `make check-perf`).

Three regression sentinels for the audit P-010 finding:

1. plan level - every rewritten id lookup must use the unique `:Node(id)` index;
2. cascade - revoking a root with ~20k descendants must finish in < 20 s;
3. gate hot path - `check_action` with 10 relied-on ids on a 60k-node graph < 100 ms.

Before the fix these failed: labelled anchors planned as *Node By Label Scan* (quadratic),
the revoke cascade timed out above ~15-20k nodes and 1000 gate supports took 3.7-5.5 s
on a 60k graph (AUDIT.md P-010). The lint side lives in tests/unit/test_query_lint.py.
"""

from __future__ import annotations

import re
import time

import pytest

import pedigree.db.queries as Q
from pedigree.db.schema import check_invariants
from pedigree.engine.gate import check_action
from pedigree.engine.revoke import revoke

pytestmark = pytest.mark.perf

# Queries rewritten for P-010 (every id anchor now matches on :Node first).
REWRITTEN_ANCHORS = (
    "Q_CORROBORATE",
    "Q_GET_SESSION",
    "Q_SESSION_READ",
    "Q_READ_WINDOW",
    "Q_SESSION_INFO",
    "Q_SUPPORT_OF",
    "Q_ACTION_DETAILS",
    "Q_MEMORY_ARTIFACTS",
    "Q_REVOCATION_SET_STATE",
    "Q_DEMO_ADD_SUPPORT",
    "Q_GATE_SUPPORT",
)

# Dummy values so GRAPH.EXPLAIN can resolve pattern-bound parameters.
_PARAMS = {
    "ids": ["x"], "m": "x", "s": "x", "id": "x", "sess": "x", "n": "x", "rid": "x",
    "memory_id": "x", "source_id": "x", "by": "human", "now": 0, "k": 10,
    "state": "done", "t": 0, "p": 0, "a": 0, "rel": "derive", "via": "sync",
}


def _explain(graph, query: str) -> str:
    params = {name: _PARAMS.get(name, "x") for name in set(re.findall(r"\$(\w+)", query))}
    return str(graph.explain(query, params))


def test_anchor_lookups_plan_on_the_node_index(fresh_graph):
    db, _tenant, gname = fresh_graph
    graph = db.select(gname)
    offenders = []
    for name in REWRITTEN_ANCHORS:
        plan = _explain(graph, getattr(Q, name))
        if "Node By Index Scan" not in plan or "Node By Label Scan" in plan:
            offenders.append(f"{name}:\n{plan}")
    assert not offenders, (
        "rewritten id anchors must plan Node By Index Scan and never Node By Label Scan:\n\n"
        + "\n\n".join(offenders)
    )


def _build_chain(db, gname: str, tenant: str, n: int, prefix: str) -> None:
    """A parent->child chain of `n` Memory nodes (FEEDS) with mirrored DERIVED_FROM."""
    db.query(
        gname,
        """
        UNWIND range(0, $n - 1) AS i
        CREATE (m:Node:Memory)
        SET m.id = $p + toString(i), m.tenant = $t, m.kind = 'fact', m.text = 'P-010 perf cell',
            m.status = 'ok', m.low_integrity = false, m.conf = [], m.conf_eff = [], m.created_at = 0
        RETURN count(m) AS n
        """,
        {"n": n, "p": prefix, "t": tenant},
        op="perf.build.nodes",
    )
    db.query(
        gname,
        """
        UNWIND range(0, $n - 2) AS i
        WITH $p + toString(i) AS pid, $p + toString(i + 1) AS cid
        MATCH (p:Node {id: pid}), (c:Node {id: cid})
        CREATE (p)-[:FEEDS]->(c), (c)-[:DERIVED_FROM]->(p)
        RETURN count(*) AS n
        """,
        {"n": n, "p": prefix},
        op="perf.build.edges",
    )


def test_revoke_20k_cascade_under_20s(fresh_graph):
    db, tenant, gname = fresh_graph
    prefix = "p010r-"
    _build_chain(db, gname, tenant, 20_000, prefix)

    t0 = time.perf_counter()
    out = revoke(db, gname, tenant, root_id=prefix + "0", reason="P-010 perf gate")
    elapsed = time.perf_counter() - t0

    assert out["state"] == "done"
    assert out["counts"]["tainted"] >= 5_000, out  # root really has >= 5k descendants
    assert out["counts"]["quarantined_left"] == 0
    assert elapsed < 20.0, f"revoke of 20k nodes took {elapsed:.1f} s (ceiling 20 s)"
    assert check_invariants(db, gname, expected_tenant=tenant) == []


def test_gate_action_10_ids_on_60k_under_100ms(fresh_graph):
    db, tenant, gname = fresh_graph
    prefix = "p010g-"
    _build_chain(db, gname, tenant, 60_000, prefix)
    db.query(
        gname,
        """
        UNWIND range(0, 9) AS i
        CREATE (m:Node:Memory)
        SET m.id = $p + 'm' + toString(i), m.tenant = $t, m.kind = 'fact', m.text = 'P-010 supported cell',
            m.status = 'preserved', m.low_integrity = false, m.conf = [], m.conf_eff = [], m.created_at = 0
        CREATE (s:Node:Source)
        SET s.id = $p + 's' + toString(i), s.tenant = $t, s.kind = 'web', s.status = 'ok',
            s.low_integrity = false, s.created_at = 0
        MERGE (m)-[c:CORROBORATED_BY]->(s) SET c.by = 'human'
        RETURN count(m) AS n
        """,
        {"p": prefix, "t": tenant},
        op="perf.build.support",
    )

    relied = [prefix + "m" + str(i) for i in range(10)]
    t0 = time.perf_counter()
    out = check_action(db, gname, {"tool": "read", "summary": "P-010 gate latency"}, relied_on=relied)
    elapsed = time.perf_counter() - t0

    assert out["decision"] == "allow", out
    assert out["checked"] == 10
    assert elapsed < 0.100, f"gate took {elapsed * 1000:.1f} ms on a 60k-node graph (ceiling 100 ms)"
