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
    return tid, tok, {"Authorization": "Bearer " + tok}


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
