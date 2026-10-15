"""Security tests for F-05 REST API (red-team)."""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.config import get_settings

ADMIN = "test-admin-secret"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("PEDIGREE_ADMIN_TOKEN", ADMIN)
    try:
        get_settings.cache_clear()
    except Exception:
        pass
    return TestClient(create_app())


def _tenant(client, tid):
    r = client.post("/admin/tenants", headers={"X-Admin-Token": ADMIN}, json={"id": tid})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_cross_tenant_token_cannot_read_graph(client):
    t1 = "sa" + uuid.uuid4().hex[:8]
    t2 = "sb" + uuid.uuid4().hex[:8]
    tok1 = _tenant(client, t1)
    tok2 = _tenant(client, t2)
    h1 = {"Authorization": "Bearer " + tok1}
    src = client.post("/v1/sources", headers=h1, json={"kind": "web", "uri": "x"}).json()["id"]
    r = client.get("/v1/blame/" + src, headers={"Authorization": "Bearer " + tok2})
    assert r.status_code == 404


def test_body_tenant_override_rejected(client):
    tid = "sc" + uuid.uuid4().hex[:8]
    tok = _tenant(client, tid)
    h = {"Authorization": "Bearer " + tok}
    r = client.post("/v1/sources", headers=h, json={"kind": "web", "tenant": "evil", "uri": "x"})
    assert r.status_code == 422


def test_malformed_content_length_not_500(client):
    tid = "sd" + uuid.uuid4().hex[:8]
    tok = _tenant(client, tid)
    h = {"Authorization": "Bearer " + tok}
    body = json.dumps({"kind": "web", "uri": "x"}).encode()
    r = client.post("/v1/sources", headers={**h, "Content-Length": "abc"}, content=body)
    assert r.status_code != 500


def test_graph_name_collision_reserved(client):
    r = client.post("/admin/tenants", headers={"X-Admin-Token": ADMIN}, json={"id": "registry"})
    assert r.status_code in (409, 422)


def test_cypher_like_id_rejected_or_not_found(client):
    tid = "se" + uuid.uuid4().hex[:8]
    tok = _tenant(client, tid)
    h = {"Authorization": "Bearer " + tok}
    for bad in ["..", "*", "ped:abc' OR 1=1 --"]:
        r = client.get("/v1/blame/" + bad, headers=h)
        assert r.status_code in (404, 400, 422)
