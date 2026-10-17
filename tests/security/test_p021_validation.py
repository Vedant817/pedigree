"""Public malformed inputs must fail before any graph mutation."""
import logging

import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings


@pytest.fixture
def boundary(fresh_graph):
    db, tenant, graph = fresh_graph
    settings = Settings(pedigree_admin_token="validation-fixture-admin")
    registry = TenantRegistry(db, settings)
    credential = registry.create_tenant(tenant)
    try:
        with TestClient(create_app(db, settings), raise_server_exceptions=False) as client:
            yield db, graph, client, {"Authorization": "Bearer " + credential.token}
    finally:
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})


def snapshot(db, graph):
    return (db.ro_query(graph, "MATCH(n) RETURN labels(n),properties(n)").result_set,
            db.ro_query(graph, "MATCH(a)-[r]->(b) RETURN a.id,type(r),b.id,properties(r)").result_set)


@pytest.mark.parametrize("bad", [
    {"type": "source", "kind": "web", "conf": 5},
    {"type": "action", "tool": "x", "artifacts": 5},
    {"type": "memory", "derived_from": "ghost"},
    {"type": "not_a_real_event"},
    {"type": "memory", "extra_canary": "ignored"},
    {"type": "source", "uri": "https://x/\u0001"},
    {"type": "memory", "text": "hidden\u0000control"},
    {"type": "source", "source_kind": "web", "kind": "file"},
])
def test_malformed_tail_rejects_entire_batch(boundary, bad):
    db, graph, client, headers = boundary
    before = snapshot(db, graph)
    response = client.post("/v1/events", headers=headers, json={"events": [
        {"type": "memory", "id": "must_not_commit", "text": "early"}, bad]})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_argument"
    assert snapshot(db, graph) == before


@pytest.mark.parametrize("path,payload", [
    ("sources", {"kind": "web", "uri": "bad\u007fpath"}),
    ("sources", {"kind": "web", "conf": [5]}),
    ("memories", {"text": "bad\u0000text"}),
    ("actions", {"tool": "x", "summary": "bad\u0001summary"}),
    ("actions", {"tool": "x", "artifacts": "file.txt"}),
    ("sessions", {"session_id": "bad id"}),
])
def test_direct_rest_uses_same_strict_fields(boundary, path, payload):
    db, graph, client, headers = boundary
    before = snapshot(db, graph)
    response = client.post("/v1/" + path, headers=headers, json=payload)
    assert response.status_code == 422, response.text
    assert snapshot(db, graph) == before


def _logged(caplog) -> str:
    return " ".join(record.getMessage() for record in caplog.records
                    if record.name == "pedigree.errors")


def test_validation_failure_logs_field_and_type_not_values(boundary, caplog):
    db, graph, client, headers = boundary
    with caplog.at_level(logging.INFO, logger="pedigree.errors"):
        response = client.post("/v1/sources", headers=headers,
                               json={"kind": "web", "stray_canary": "http://canary.invalid"})
    assert response.status_code == 422, response.text
    assert "stray_canary" not in response.text          # the envelope stays opaque
    logged = _logged(caplog)
    assert response.json()["error"]["correlation_id"] in logged
    assert "stray_canary" in logged                      # field path is diagnosable
    assert "extra_forbidden" in logged
    assert "canary.invalid" not in logged                # submitted values are never logged


def test_typed_rejection_logs_the_authored_reason(boundary, caplog):
    db, graph, client, headers = boundary
    with caplog.at_level(logging.INFO, logger="pedigree.errors"):
        response = client.post("/admin/tenants", json={"id": "registry"},
                               headers={"x-admin-token": "validation-fixture-admin"})
    assert response.status_code == 422, response.text
    logged = _logged(caplog)
    assert response.json()["error"]["correlation_id"] in logged
    assert "reserved tenant id" in logged
