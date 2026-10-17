"""P-023: tenant isolation and concurrency.

The tenant boundary is the product's trust boundary. These tests try to break it
with concurrent interleavings and cross-tenant id reuse, against the real FalkorDB.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid

import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings, graph_name
from pedigree.db.client import Db
from pedigree.engine.ingest import get_node_statuses, record_source, remember
from pedigree.mcp_server import build_mcp

ADMIN = "p023-fixture-admin"


@pytest.fixture
def two_tenants():
    settings = Settings(pedigree_admin_token=ADMIN)
    db = Db(settings)
    reg = TenantRegistry(db, settings)
    tid_a = "isoa" + uuid.uuid4().hex[:8]
    tid_b = "isob" + uuid.uuid4().hex[:8]
    ca = reg.create_tenant(tid_a)
    cb = reg.create_tenant(tid_b)
    ga, gb = graph_name(tid_a), graph_name(tid_b)
    from pedigree.db.schema import ensure_schema
    ensure_schema(db, ga)
    ensure_schema(db, gb)
    try:
        yield {
            "db": db, "settings": settings, "registry": reg,
            "a": {"id": tid_a, "graph": ga, "cred": ca},
            "b": {"id": tid_b, "graph": gb, "cred": cb},
        }
    finally:
        for t in (tid_a, tid_b):
            try:
                db.select(graph_name(t)).delete()
            except Exception:  # noqa: BLE001 - missing graph raises
                pass
            db.query(reg.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": t})


def _headers(cred):
    return {"Authorization": "Bearer " + cred.operator_token}


def _seed(db, graph, tenant, *, tag):
    """A small lineage: untrusted source -> memory. Returns (source_id, memory_id)."""
    src = f"src-{tag}"
    mem = f"mem-{tag}"
    record_source(db, graph, tenant, id=src, kind="web", uri=f"uri-{tag}-secret",
                  integrity="untrusted")
    remember(db, graph, tenant, id=mem, text=f"memory {tag}", derived_from=[src])
    return src, mem


def _run(coro):
    return asyncio.run(coro)


def test_id_taking_routes_are_covered(two_tenants):
    """Guard: every /v1 route with a path parameter must be in the cross-tenant matrix."""
    db = two_tenants["db"]
    settings = two_tenants["settings"]
    app = create_app(db, settings)
    id_paths = sorted(p for p in app.openapi()["paths"]
                      if "{" in p and p.startswith("/v1/"))
    expected = {"/v1/blame/{node_id}", "/v1/impact/{node_id}"}
    assert set(id_paths) == expected, f"untested id-taking routes: {set(id_paths) - expected}"


def test_cross_tenant_rest_ids_return_not_in_graph(two_tenants):
    db = two_tenants["db"]
    settings = two_tenants["settings"]
    t = two_tenants
    src_a, _ = _seed(db, t["a"]["graph"], t["a"]["id"], tag="A")
    src_b, _ = _seed(db, t["b"]["graph"], t["b"]["id"], tag="B")

    with TestClient(create_app(db, settings), raise_server_exceptions=False) as client:
        hb = _headers(t["b"]["cred"])

        # blame / impact: unknown id -> 404 not_in_graph
        for path in (f"/v1/blame/{src_a}", f"/v1/impact/{src_a}"):
            r = client.get(path, headers=hb)
            assert r.status_code == 404, (path, r.status_code, r.text)
            assert r.json().get("error", {}).get("code") == "not_in_graph", r.text
            assert "uri-A-secret" not in r.text
            assert t["a"]["id"] not in r.text or t["a"]["id"] == t["b"]["id"]

        # revoke root_id not in B's graph -> 404
        r = client.post("/v1/revoke", headers=hb, json={"root_id": src_a, "reason": "x"})
        assert r.status_code == 404, r.text
        assert r.json().get("error", {}).get("code") == "not_in_graph", r.text

        # gate relied_on A's id: computed from B's graph only, no leak
        r = client.post("/v1/gate", headers=hb,
                        json={"action": {"tool": "read_file", "summary": "x"},
                              "relied_on": [src_a]})
        assert r.status_code == 200, r.text
        body = r.text
        assert "uri-A-secret" not in body
        assert t["a"]["id"] not in body or t["a"]["id"] == t["b"]["id"]


def test_cross_tenant_mcp_ids_return_not_in_graph(two_tenants):
    db = two_tenants["db"]
    settings = two_tenants["settings"]
    t = two_tenants
    src_a, _ = _seed(db, t["a"]["graph"], t["a"]["id"], tag="A")
    src_b, _ = _seed(db, t["b"]["graph"], t["b"]["id"], tag="B")

    srv_b = build_mcp(db, settings, t["b"]["id"], t["b"]["cred"].operator_token).server

    async def invoke(server, name, args):
        res = await server.call_tool(name, args)
        return json.loads(res.content[0].text)

    common_b = {"tenant_id": t["b"]["id"], "token": t["b"]["cred"].operator_token}

    # blame / impact / revoke: not_in_graph
    for tool, key in (("pedigree_blame", "node_id"), ("pedigree_impact", "node_id")):
        out = _run(invoke(srv_b, tool, {**common_b, key: src_a}))
        assert out.get("ok") is False, out
        assert (out.get("error") or {}).get("code") == "not_in_graph", out
        assert "uri-A-secret" not in json.dumps(out)

    out = _run(invoke(srv_b, "pedigree_revoke", {**common_b, "root_id": src_a, "reason": "x"}))
    assert out.get("ok") is False, out
    assert (out.get("error") or {}).get("code") == "not_in_graph", out

    # check_action: computed from B's graph, no leak
    out = _run(invoke(srv_b, "pedigree_check_action",
                      {"token": t["b"]["cred"].operator_token, "tool": "read_file",
                       "summary": "x", "relied_on": [src_a]}))
    assert out.get("ok") is True, out
    assert "uri-A-secret" not in json.dumps(out)
    assert t["a"]["id"] not in json.dumps(out) or t["a"]["id"] == t["b"]["id"]


def test_access_log_does_not_leak_other_tenant(two_tenants, caplog):
    db = two_tenants["db"]
    settings = two_tenants["settings"]
    t = two_tenants
    src_a, _ = _seed(db, t["a"]["graph"], t["a"]["id"], tag="A")

    with TestClient(create_app(db, settings), raise_server_exceptions=False) as client:
        with caplog.at_level(logging.INFO, logger="pedigree.access"):
            r = client.get(f"/v1/blame/{src_a}", headers=_headers(t["b"]["cred"]))
        assert r.status_code == 404
        lines = [rec.getMessage() for rec in caplog.records if rec.name == "pedigree.access"]
        assert lines
        for line in lines:
            assert "uri-A-secret" not in line
            assert t["a"]["id"] not in line or t["a"]["id"] == t["b"]["id"]


def test_concurrent_revoke_does_not_cross_tenants(two_tenants):
    db = two_tenants["db"]
    t = two_tenants
    src_a, mem_a = _seed(db, t["a"]["graph"], t["a"]["id"], tag="A")
    src_b, mem_b = _seed(db, t["b"]["graph"], t["b"]["id"], tag="B")

    errors = []

    def worker(tenant, graph, src, mem):
        try:
            from pedigree.engine.revoke import revoke
            revoke(db, graph, tenant, root_id=src, reason="iso")
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    ta = threading.Thread(target=worker, args=(t["a"]["id"], t["a"]["graph"], src_a, mem_a))
    tb = threading.Thread(target=worker, args=(t["b"]["id"], t["b"]["graph"], src_b, mem_b))
    ta.start()
    tb.start()
    ta.join()
    tb.join()
    assert not errors, errors

    sa = get_node_statuses(db, t["a"]["graph"], [src_a, mem_a])
    sb = get_node_statuses(db, t["b"]["graph"], [src_b, mem_b])
    assert sa[src_a] == "revoked" and sa[mem_a] == "tainted", sa
    assert sb[src_b] == "revoked" and sb[mem_b] == "tainted", sb
    # no cross-contamination: each graph holds only its own nodes
    rows_a = db.ro_query(t["a"]["graph"], "MATCH (n:Node) RETURN n.id", {}).result_set or []
    rows_b = db.ro_query(t["b"]["graph"], "MATCH (n:Node) RETURN n.id", {}).result_set or []
    ids_a = {r[0] for r in rows_a}
    ids_b = {r[0] for r in rows_b}
    assert src_b not in ids_a and src_a not in ids_b
    assert mem_b not in ids_a and mem_a not in ids_b


def test_concurrent_ingest_does_not_cross_tenants(two_tenants):
    db = two_tenants["db"]
    t = two_tenants
    before_a = db.ro_query(t["a"]["graph"], "MATCH (n:Node) RETURN count(n)", {}).result_set[0][0]
    before_b = db.ro_query(t["b"]["graph"], "MATCH (n:Node) RETURN count(n)", {}).result_set[0][0]

    def worker(graph, tenant, tag):
        record_source(db, graph, tenant, id=f"concurrent-{tag}", kind="web", uri=f"u-{tag}")

    threads = [
        threading.Thread(target=worker, args=(t["a"]["graph"], t["a"]["id"], "a1")),
        threading.Thread(target=worker, args=(t["a"]["graph"], t["a"]["id"], "a2")),
        threading.Thread(target=worker, args=(t["b"]["graph"], t["b"]["id"], "b1")),
        threading.Thread(target=worker, args=(t["b"]["graph"], t["b"]["id"], "b2")),
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    after_a = db.ro_query(t["a"]["graph"], "MATCH (n:Node) RETURN count(n)", {}).result_set[0][0]
    after_b = db.ro_query(t["b"]["graph"], "MATCH (n:Node) RETURN count(n)", {}).result_set[0][0]
    assert after_a == before_a + 2, (before_a, after_a)
    assert after_b == before_b + 2, (before_b, after_b)
    # no cross-contamination of the new ids
    ids_a = {r[0] for r in (db.ro_query(t["a"]["graph"], "MATCH (n:Node) RETURN n.id", {}).result_set or [])}
    ids_b = {r[0] for r in (db.ro_query(t["b"]["graph"], "MATCH (n:Node) RETURN n.id", {}).result_set or [])}
    assert "concurrent-b1" not in ids_a and "concurrent-b2" not in ids_a
    assert "concurrent-a1" not in ids_b and "concurrent-a2" not in ids_b
