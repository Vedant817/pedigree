"""End-to-end tests for the HTTP API (F-05). They run against the REAL FalkorDB via a tenant graph."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app

ADMIN_TOKEN = "test-admin-secret"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("PEDIGREE_ADMIN_TOKEN", ADMIN_TOKEN)
    from pedigree.config import get_settings
    try:
        get_settings.cache_clear()
    except Exception:
        pass
    app = create_app()
    return TestClient(app)


@pytest.fixture
def tenant(client):
    tid = "t" + uuid.uuid4().hex[:10]
    r = client.post("/admin/tenants", headers={"X-Admin-Token": ADMIN_TOKEN}, json={"id": tid})
    assert r.status_code == 200, r.text
    try:
        yield tid, r.json()["token"]
    finally:
        db = client.app.state.db
        registry = client.app.state.registry
        graph = "ped:" + tid
        try:
            if graph in db.list_graphs():
                db.select(graph).delete()
        finally:
            db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tid})


def _h(tok):
    return {"Authorization": "Bearer " + tok}


def test_health_and_ready(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"X-Admin-Token": ADMIN_TOKEN}).status_code == 200


def test_auth_without_token_is_rejected(client):
    r = client.get("/v1/blame/x")
    assert r.status_code == 401


def test_invalid_token_is_rejected(client):
    r = client.get("/v1/blame/x", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


def test_tenant_override_in_body_is_rejected(client, tenant):
    tid, tok = tenant
    h = _h(tok)
    r = client.post("/v1/sources", headers=h, json={"kind": "web", "tenant": "evil", "uri": "x"})
    assert r.status_code == 422


def test_source_lifecycle_and_revocation(client, tenant):
    tid, tok = tenant
    h = _h(tok)
    src = client.post("/v1/sources", headers=h, json={"kind": "web", "uri": "http://example/x", "title": "x"}).json()
    sid = src["id"]
    mem = client.post("/v1/memories", headers=h, json={"text": "summary", "derived_from": [sid]}).json()
    mem["id"]
    rev = client.post("/v1/revoke", headers=h, json={"root_id": sid, "reason": "bad"})
    assert rev.status_code == 200, rev.text
    assert rev.json()["counts"]["tainted"] == 1
    rep = client.get("/v1/stats", headers=h).json()
    assert rep
    impact = client.get("/v1/impact/" + sid, headers=h).json()
    assert impact
    bad = client.get("/v1/blame/ghost", headers=h)
    assert bad.status_code == 404


def test_tenant_isolation(client):
    tid1 = "ta" + uuid.uuid4().hex[:8]
    tid2 = "tb" + uuid.uuid4().hex[:8]
    owned = []
    try:
        r1 = client.post("/admin/tenants", headers={"X-Admin-Token": ADMIN_TOKEN}, json={"id": tid1})
        if r1.status_code == 200:
            owned.append(tid1)
        r2 = client.post("/admin/tenants", headers={"X-Admin-Token": ADMIN_TOKEN}, json={"id": tid2})
        if r2.status_code == 200:
            owned.append(tid2)
        tok1 = r1.json()["token"]
        tok2 = r2.json()["token"]
        h1 = {"Authorization": "Bearer " + tok1}
        h2 = {"Authorization": "Bearer " + tok2}
        src = client.post("/v1/sources", headers=h1, json={"kind": "web", "uri": "x"}).json()
        res = client.get("/v1/blame/" + src["id"], headers=h2)
        assert res.status_code == 404
        assert client.get("/healthz").status_code == 200
    finally:
        db = client.app.state.db
        registry = client.app.state.registry
        for tid in owned:
            graph = "ped:" + tid
            try:
                if graph in db.list_graphs():
                    db.select(graph).delete()
            finally:
                db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tid})


def test_revoke_is_idempotent(client, tenant):
    tid, tok = tenant
    h = {"Authorization": "Bearer " + tok}
    src = client.post("/v1/sources", headers=h, json={"kind": "web", "uri": "x"}).json()["id"]
    client.post("/v1/memories", headers=h, json={"text": "derived", "derived_from": [src]})
    r1 = client.post("/v1/revoke", headers=h, json={"root_id": src, "reason": "first"}).json()
    r2 = client.post("/v1/revoke", headers=h, json={"root_id": src, "reason": "second"}).json()
    assert r1["counts"]["tainted"] >= 1
    assert r2.get("idempotent") is True or r2.get("state") == "done"
