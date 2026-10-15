"""F-15 / E5 - tenant isolation and concurrency against a real FalkorDB.

1. API-level isolation matrix: tenant A's token cannot read, revoke, gate or corroborate
   anything in tenant B's graph, and cross-tenant ids fail closed (never "safe", never data).
2. Threaded stress: >= 20 tenants x 8 writer threads, then every graph must satisfy the
   invariant checker, hold exactly the nodes that tenant wrote, and contain zero foreign-tenant
   nodes (docs/05 AT2.3).
3. Revoke-during-ingest race on one graph: the barrier/fixpoint must still resolve to a state
   the invariant checker accepts (no half-revoked structure leaks through).
"""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings, graph_name
from pedigree.db.schema import check_invariants, ensure_schema
from pedigree.engine.ingest import get_node_statuses, record_action, record_source, remember
from pedigree.engine.revoke import revoke

ADMIN = "f15-admin"
TENANTS = 20
WRITERS = 8
NODES_PER_WRITER = 6


@pytest.fixture
def app_client():
    settings = Settings(pedigree_admin_token=ADMIN)
    from pedigree.config import get_settings
    from pedigree.db.client import Db

    get_settings.cache_clear()
    db = Db(settings)
    registry = TenantRegistry(db, settings)
    client = TestClient(create_app(db, settings))
    yield db, registry, client
    for rec in registry.list_tenants():
        try:
            db.select(f"ped:{rec.tenant_id}").delete()
        except Exception:  # noqa: BLE001 - an empty graph raises on delete (FalkorDB)
            pass
        db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": rec.tenant_id})


def _mk_tenant(registry, client):
    tid = "i" + "".join(__import__("secrets").choice("0123456789abcdefghijklmnopqrstuvwxyz")
                        for _ in range(11))
    r = client.post("/admin/tenants", headers={"X-Admin-Token": ADMIN}, json={"id": tid})
    assert r.status_code == 200, r.text
    return tid, r.json()["token"]


def test_api_isolation_matrix(app_client):
    db, registry, client = app_client
    tid_a, tok_a = _mk_tenant(registry, client)
    tid_b, tok_b = _mk_tenant(registry, client)
    ha = {"Authorization": "Bearer " + tok_a}
    hb = {"Authorization": "Bearer " + tok_b}
    src = client.post("/v1/sources", headers=ha, json={"kind": "web", "uri": "http://a"}).json()
    mem = client.post("/v1/memories", headers=ha, json={"text": "secret", "derived_from": [src["id"]]}).json()
    sid = src["id"]

    # A's ids are invisible to B (not_in_graph, never empty-but-ok)
    assert client.get("/v1/blame/" + sid, headers=hb).status_code == 404
    assert client.get("/v1/impact/" + sid, headers=hb).status_code == 404
    gate = client.post("/v1/gate", headers=hb, json={"action": {"tool": "Read"},
                                                    "relied_on": [sid]})
    assert gate.status_code == 200
    assert gate.json()["decision"] == "reverify"      # unknown lineage is never "safe"
    # B cannot revoke, corroborate or read A's nodes through any write path
    assert client.post("/v1/revoke", headers=hb, json={"root_id": sid, "reason": "x"}).status_code == 404
    assert client.post("/v1/corroborate", headers=hb,
                       json={"memory_id": mem["id"], "source_id": sid}).status_code == 404
    # A's own graph is untouched by all of the above
    assert get_node_statuses(db, f"ped:{tid_a}", [sid, mem["id"]]) == {sid: "ok", mem["id"]: "ok"}
    assert check_invariants(db, f"ped:{tid_a}", expected_tenant=tid_a) == []
    assert check_invariants(db, f"ped:{tid_b}", expected_tenant=tid_b) == []


def test_threaded_stress_isolation_and_invariants(app_client):
    """docs/05 AT2.3: >= 20 tenants x 8 writer threads, invariants OK, zero cross-tenant nodes."""
    db, registry, client = app_client
    credentials = [_mk_tenant(registry, client) for _ in range(TENANTS)]
    for tid, _tok in credentials:
        # the engine assumes its schema exists (every API request runs ensure_schema)
        ensure_schema(db, f"ped:{tid}")
    errors: list[str] = []

    def work(tid: str, token: str, writer: int) -> None:
        try:
            gname = graph_name(tid)
            for i in range(NODES_PER_WRITER):
                src = record_source(db, gname, tid, kind="web", uri=f"http://{tid}/{i}")
                remember(db, gname, tid, text="t", derived_from=[src.id])
                record_action(db, gname, tid, tool="Read", summary="s",
                              relied_on=[src.id], effect="reversible", risk="low")
        except Exception as exc:  # noqa: BLE001 - collected and reported by the assertion below
            errors.append(f"{tid}:{writer}: {type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=work, args=(tid, tok, w))
               for tid, tok in credentials for w in range(WRITERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert not errors, errors[:5]

    for tid, _tok in credentials:
        gname = f"ped:{tid}"
        assert check_invariants(db, gname, expected_tenant=tid) == [], tid
        # 6 distinct uris -> 6 Sources (the 8 identical writers converge on the same node
        # because Source identity is derived, ADR-008); memories and actions are per-call.
        expected = 6 + WRITERS * NODES_PER_WRITER * 2
        rows = db.ro_query(gname, "MATCH (n) RETURN count(n), count(DISTINCT n.tenant)").result_set[0]
        labels = db.ro_query(gname, "MATCH (n) RETURN labels(n), count(n)").result_set
        assert rows[1] == 1, (tid, rows)
        assert rows[0] == expected, (tid, rows, labels)
        foreign = db.ro_query(gname, "MATCH (n) WHERE n.tenant <> $t RETURN count(n)",
                              {"t": tid}).result_set[0][0]
        assert foreign == 0, tid


def test_revoke_during_ingest_stays_consistent(app_client):
    """A revoke racing ingest must leave a graph the invariant checker accepts (no torn state)."""
    db, registry, client = app_client
    tid, tok = _mk_tenant(registry, client)
    from pedigree.config import graph_name
    gname = graph_name(tid)
    for n in range(30):
        record_source(db, gname, tid, kind="web", uri=f"http://race/{n}")
    record_source(db, gname, tid, id="race_root", kind="web", uri="http://race/root")
    errors: list[str] = []

    def writer():
        try:
            for _ in range(15):
                remember(db, gname, tid, text="racing", derived_from=["race_root"])
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")

    def revoker():
        try:
            revoke(db, gname, tid, root_id="race_root", reason="race")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"revoke {type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=writer), threading.Thread(target=writer),
               threading.Thread(target=revoker)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    # a typed error from the barrier (conflict/retry) is acceptable; a crash is not
    assert not [e for e in errors if "Conflict" not in e], errors[:5]
    violations = check_invariants(db, gname, expected_tenant=tid)
    assert violations == [], violations
    statuses = get_node_statuses(db, gname, ["race_root"])
    assert statuses["race_root"] == "revoked"
