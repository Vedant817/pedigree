from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app

ADMIN = "test-admin-secret"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("PEDIGREE_ADMIN_TOKEN", ADMIN)
    from pedigree.config import get_settings

    try:
        get_settings.cache_clear()
    except Exception:
        pass
    return TestClient(create_app())


@pytest.fixture
def tenant(client):
    tid = "te" + uuid.uuid4().hex[:10]
    r = client.post("/admin/tenants", headers={"X-Admin-Token": ADMIN}, json={"id": tid})
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    try:
        yield tid, tok, {"Authorization": "Bearer " + tok}
    finally:
        from pedigree.config import graph_name
        registry = client.app.state.registry
        try:
            if graph_name(tid) in registry.db.list_graphs():
                registry.db.select(graph_name(tid)).delete()
        finally:
            registry.db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tid})


def test_events_lifecycle(client, tenant):
    tid, tok, h = tenant
    ev = {
        "runtime": "opencode",
        "session_id": "s1",
        "events": [
            {"type": "ensure_session", "session_id": "s1"},
            {"type": "source", "kind": "web", "uri": "http://x", "title": "x"},
            {"type": "memory", "text": "summary", "derived_from": []},
            {"type": "action", "tool": "git commit", "summary": "c"},
        ],
    }
    r = client.post("/v1/events", headers=h, json=ev)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["created"], list)
    assert len(body["created"]) == 3

    inv = client.get("/v1/invariants", headers=h).json()
    assert "violations" in inv
    lookup = client.get("/v1/artifacts/lookup?key=none", headers=h)
    assert lookup.status_code == 200


def test_events_requires_auth(client):
    r = client.post("/v1/events", json={"events": []})
    assert r.status_code == 401


def test_events_rejects_oversized_batch(client, tenant):
    _tid, _tok, h = tenant
    ev = {"runtime": "generic", "session_id": "s9", "events": [
        {"type": "session_read", "session_id": "s9", "node_id": "n"} for _ in range(501)]}
    r = client.post("/v1/events", headers=h, json=ev)
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "too_large"


def test_events_rejects_unknown_kinds(client, tenant):
    _tid, _tok, h = tenant
    r = client.post("/v1/events", headers=h, json={
        "runtime": "generic", "session_id": "s8",
        "events": [{"type": "not_a_real_event", "x": 1}]})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_argument"


def test_events_capture_ids_converge_on_the_same_source(client, tenant):
    """ADR-008: the artifact names the node; two captures of the same uri converge."""
    _tid, _tok, h = tenant
    body = {"events": [{"type": "source", "kind": "web", "uri": "u"}]}
    first = client.post("/v1/events", headers=h, json=body).json()["created"]
    second = client.post("/v1/events", headers=h, json=body).json()["created"]
    assert first == second and len(first) == 1


def test_events_id_conflict_for_different_content(client, tenant):
    _tid, _tok, h = tenant
    assert client.post("/v1/events", headers=h, json={
        "events": [{"type": "source", "kind": "web", "id": "dup_evt2", "uri": "u1"}]}).status_code == 200
    r = client.post("/v1/events", headers=h, json={
        "events": [{"type": "source", "kind": "web", "id": "dup_evt2", "uri": "u2"}]})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"
