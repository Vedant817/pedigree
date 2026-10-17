"""P-012 invariant I-a: a node carrying `revoked_at` must have `status='revoked'`.

Negative test for the shipped check (`Q_INV_REVOKED_ORPHAN` in `check_invariants`), independent
of the engine code path: the corruption is a raw `SET` that reproduces exactly the shape the old
blanket-reset `reinstate` left behind (`B.status='ok'` + `revoked_at` still set). A legitimate
reinstate clears the marker, so the check must stay silent there.
"""

from __future__ import annotations

from pedigree.db.queries import Q_INV_REVOKED_ORPHAN
from pedigree.db.schema import check_invariants
from pedigree.engine.ingest import record_source, remember
from pedigree.engine.revoke import reinstate, revoke


def _chain(db, tenant, gname):
    record_source(db, gname, tenant, kind="web", id="A", uri="https://t/a", title="a")
    remember(db, gname, tenant, text="B", id="B", derived_from=["A"])
    remember(db, gname, tenant, text="Cc", id="Cc", derived_from=["B"])


def _ia_count(db, gname) -> int:
    rows = db.ro_query(gname, Q_INV_REVOKED_ORPHAN, {}).result_set or []
    return int(rows[0][0]) if rows else 0


def test_ia_flags_a_hand_corrupted_clobbered_root(fresh_graph):
    db, tenant, gname = fresh_graph
    _chain(db, tenant, gname)
    revoke(db, gname, tenant, root_id="A", reason="bad A")
    revoke(db, gname, tenant, root_id="B", reason="bad B")
    assert check_invariants(db, gname, expected_tenant=tenant) == []
    assert _ia_count(db, gname) == 0

    # the corruption the old reinstate left: B is 'ok' but still carries its revoke marker
    db.query(gname, "MATCH (n:Node {id:'B'}) SET n.status='ok'", {}, op="test.corrupt")
    marker = db.ro_query(gname, "MATCH (n:Node {id:'B'}) RETURN n.revoked_at", {}).result_set
    assert marker and marker[0][0] is not None, "the corruption must keep revoked_at set"

    assert _ia_count(db, gname) == 1
    violations = check_invariants(db, gname, expected_tenant=tenant)
    assert any("not marked revoked" in v for v in violations), violations

    # restoring the status makes the graph healthy again (the check is not sticky)
    db.query(gname, "MATCH (n:Node {id:'B'}) SET n.status='revoked'", {}, op="test.repair")
    assert check_invariants(db, gname, expected_tenant=tenant) == []


def test_ia_stays_silent_for_a_legitimately_reinstated_root(fresh_graph):
    """F2 of the review: a reinstate clears `revoked_at`, so rows/status history must not be
    used for this check - it would false-positive on the reinstated root."""
    db, tenant, gname = fresh_graph
    _chain(db, tenant, gname)
    revoke(db, gname, tenant, root_id="A", reason="bad A")
    reinstate(db, gname, tenant, root_id="A")
    assert _ia_count(db, gname) == 0
    assert check_invariants(db, gname, expected_tenant=tenant) == []
