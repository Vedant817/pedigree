"""P-012: `reinstate` must not un-revoke independent roots (FIX_PROMPT B2).

Deterministic repro (audit A->B->Cc case): revoke A; revoke B; reinstate A -> want
A=ok, B=revoked, Cc=tainted. Before the fix every node went back to 'ok' (P-012 old bug).
"""
from __future__ import annotations

import uuid

from pedigree.api.registry import TenantRegistry
from pedigree.config import graph_name
from pedigree.db.client import Db
from pedigree.db.schema import check_invariants
from pedigree.engine.ingest import record_source, remember
from pedigree.engine.revoke import reinstate, revoke


def _build_chain(db, tid):
    gname = graph_name(tid)
    registry = TenantRegistry(db)
    registry.create_tenant(tid)
    # A (source, trusted) -> B (memory) -> Cc (memory)
    record_source(db, gname, tid, kind="web", id="A", uri="https://t/a", title="a", integrity="trusted")
    remember(db, gname, tid, text="B", id="B", derived_from=["A"])
    remember(db, gname, tid, text="Cc", id="Cc", derived_from=["B"])
    return gname


def _drop(db, gname, tid):
    registry = TenantRegistry(db)
    try:
        db.select(gname).delete()
    except Exception:  # noqa: BLE001 - missing graph raises
        pass
    db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tid})


def test_reinstate_does_not_unrevoke_independent_root():
    db = Db()
    tid = "p012" + uuid.uuid4().hex[:8]
    gname = _build_chain(db, tid)
    try:
        revoke(db, gname, tid, root_id="A", reason="bad")
        revoke(db, gname, tid, root_id="B", reason="bad too")
        out = reinstate(db, gname, tid, root_id="A")
        assert out.get("dry_run") is False or out.get("dry_run") is None
        # nodes
        def status(node_id):
            return db.ro_query(gname, "MATCH (n:Node {id:$id}) RETURN n.status", {"id": node_id}).result_set[0][0]
        assert status("A") == "ok", status("A")
        assert status("B") == "revoked", status("B")
        assert status("Cc") == "tainted", status("Cc")
        assert check_invariants(db, gname, tid) == []
    finally:
        _drop(db, gname, tid)


def test_reinstate_remaining_root_stays_revoked_dry_run():
    db = Db()
    tid = "p012" + uuid.uuid4().hex[:8]
    gname = _build_chain(db, tid)
    try:
        revoke(db, gname, tid, root_id="A", reason="bad")
        revoke(db, gname, tid, root_id="B", reason="bad too")
        dry = reinstate(db, gname, tid, root_id="A", dry_run=True)
        assert dry["dry_run"] is True
        assert dry["remaining_roots"] == 1  # B stays
    finally:
        _drop(db, gname, tid)
