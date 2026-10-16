"""Independent P-029 adversarial HTTP checks against the real DB fixture."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings, graph_name
from pedigree.errors import NotFoundInGraph

ADMIN = "qa-p029-synthetic-admin"


def client_for(db, **changes):
    values = dict(_env_file=None, pedigree_env="production", pedigree_admin_token=ADMIN,
                  pedigree_public_docs=False)
    values.update(changes)
    return TestClient(create_app(db=db, settings=Settings(**values)), raise_server_exceptions=False)


@pytest.mark.parametrize("header", [None, "", "wrong", b"\xe9"])
def test_metrics_rejects_unauthorized_headers(db, header):
    headers = {} if header is None else {"X-Admin-Token": header}
    response = client_for(db).get("/metrics", headers=headers)
    assert response.status_code == 401, f"status={response.status_code}; expected 401"
    assert response.json()["error"]["code"] == "unauthorized"


def test_metrics_requires_configured_secret_and_accepts_operator(db):
    assert client_for(db, pedigree_env="dev", pedigree_admin_token="").get("/metrics").status_code == 401
    response = client_for(db).get("/metrics", headers={"X-Admin-Token": ADMIN})
    assert response.status_code == 200
    assert "python_info" in response.text
    assert "text/plain" in response.headers["content-type"]


@pytest.mark.parametrize("env, public, status", [
    ("production", False, 404), ("production", True, 200),
    ("dev", False, 200), ("test", False, 200), ("local", False, 200),
])
def test_docs_visibility(db, env, public, status):
    response = client_for(db, pedigree_env=env, pedigree_public_docs=public).get("/docs")
    assert response.status_code == status


@pytest.mark.parametrize("path", ["/redoc", "/openapi.json"])
def test_production_has_no_alternative_public_docs(db, path):
    response = client_for(db).get(path)
    assert response.status_code == 404, f"{path}: status={response.status_code}; expected 404"


def test_bearer_whitespace_and_metrics_agent_boundary(db):
    tenant = "p029" + uuid.uuid4().hex[:10]
    registry = TenantRegistry(db)
    credential = registry.create_tenant(tenant)
    client = client_for(db)
    try:
        valid = {"Authorization": "Bearer " + credential.token}
        assert client.get("/v1/invariants", headers=valid).status_code == 200
        for prefix, suffix in [("Bearer  ", ""), ("Bearer ", " "), ("Bearer\t", ""), ("bearer ", "")]:
            response = client.get("/v1/invariants", headers={"Authorization": prefix + credential.token + suffix})
            assert response.status_code == 401
        assert client.get("/metrics", headers=valid).status_code == 401
    finally:
        if graph_name(tenant) in db.list_graphs():
            db.select(graph_name(tenant)).delete()
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})


@pytest.mark.parametrize("field", ["read_timeout_ms", "write_timeout_ms"])
def test_timeout_boundaries(field):
    for value in [0, -1, 60001]:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{field: value})
    for value in [1, 60000]:
        assert getattr(Settings(_env_file=None, **{field: value}), field) == value


@pytest.mark.parametrize("tenant", ["../../etc", "ped:abc", "ABC", "ab", "a" * 25])
def test_admin_rejects_graph_name_escape(db, tenant):
    response = client_for(db).post("/admin/tenants", headers={"X-Admin-Token": ADMIN}, json={"id": tenant})
    assert response.status_code in (400, 422)


@pytest.mark.parametrize("cap", [0, -1, 1000001])
def test_admin_rejects_cap_outside_bounds(db, cap):
    tenant = "p029" + uuid.uuid4().hex[:10]
    response = client_for(db).post("/admin/tenants", headers={"X-Admin-Token": ADMIN},
                                 json={"id": tenant, "node_cap": cap})
    assert response.status_code in (400, 422)
    with pytest.raises(NotFoundInGraph, match="tenant not found"):
        TenantRegistry(db).get_record(tenant)


def test_admin_accepts_minimum_cap(db):
    tenant = "p029" + uuid.uuid4().hex[:10]
    registry = TenantRegistry(db)
    try:
        response = client_for(db).post("/admin/tenants", headers={"X-Admin-Token": ADMIN},
                                      json={"id": tenant, "node_cap": 1})
        assert response.status_code == 200
        assert registry.get_record(tenant).node_cap == 1
    finally:
        if graph_name(tenant) in db.list_graphs():
            db.select(graph_name(tenant)).delete()
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})
