"""P-024: quarantined stragglers are repaired by `reconcile` (FIX_PROMPT B3)."""
from __future__ import annotations

import uuid

from pedigree.api.registry import TenantRegistry
from pedigree.config import graph_name
from pedigree.db.schema import check_invariants
from pedigree.engine.revoke import reconcile


def _tenant(db):
    reg = TenantRegistry(db)
    tid = "rc" + uuid.uuid4().hex[:8]
    reg.create_tenant(tid)
    return reg, tid


def _drop(db, reg, tid):
    try:
        db.select(graph_name(tid)).delete()
    except Exception:  # noqa: BLE001
        pass
    db.query(reg.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tid})


def test_reconcile_repairs_quarantined_straggler(db):
    reg, tid = _tenant(db)
    gname = graph_name(tid)
    try:
        db.query(gname, "CREATE (:Node:Memory {id:$id, tenant:$t, mkind:'fact', text:'', "
                        "kind:'fact', source:'x', status:'quarantined'})",
                 {"id": "m1", "t": tid}, op="test.seed")
        inv_before = check_invariants(db, gname, tid)
        assert any("quarantined node without a running Revocation" in v for v in inv_before), inv_before
        out = reconcile(db, gname)
        assert out.get("reconciled") == 1, out
        _rows = db.ro_query(gname, "MATCH (n:Node {status:'quarantined'}) RETURN count(n) AS n",
                             {}, op="test.q").result_set
        quarantined = int(_rows[0][0]) if _rows else 0
        assert quarantined == 0, quarantined
        inv_after = check_invariants(db, gname, tid)
        assert not any("quarantined node without a running Revocation" in v for v in inv_after), inv_after
    finally:
        _drop(db, reg, tid)


def test_reconcile_is_noop_on_healthy_graph(db):
    reg, tid = _tenant(db)
    gname = graph_name(tid)
    try:
        out = reconcile(db, gname)
        assert out.get("reconciled") == 0, out
        _rows = db.ro_query(gname, "MATCH (n:Node {status:'quarantined'}) RETURN count(n) AS n",
                             {}, op="test.q").result_set
        quarantined = int(_rows[0][0]) if _rows else 0
        assert quarantined == 0
    finally:
        _drop(db, reg, tid)
