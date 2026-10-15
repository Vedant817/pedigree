"""Independent F-09 API/static trust-boundary checks, not browser acceptance."""
import uuid

import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings, graph_name
from pedigree.db.schema import ensure_schema
from pedigree.engine.ingest import corroborate, record_source, remember


@pytest.fixture
def workspace(fresh_graph):
    db, tenant, graph = fresh_graph
    settings = Settings()
    registry = TenantRegistry(db, settings)
    credential = registry.create_tenant(tenant)
    try:
        yield db, tenant, graph, registry, TestClient(create_app(db, settings)), {
            "Authorization": "Bearer " + credential.token}
    finally:
        db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": tenant})


def test_qa_graph_scope_ignores_attacker_query_tenant(workspace):
    db, tenant, graph, _, client, headers = workspace
    other = "qa" + uuid.uuid4().hex[:10]
    other_graph = graph_name(other)
    ensure_schema(db, other_graph)
    try:
        record_source(db, graph, tenant, id="mine", kind="file")
        record_source(db, other_graph, other, id="private_other", kind="file")
        response = client.get(f"/v1/graph/view?tenant={other}&graph_name={other_graph}", headers=headers)
        assert response.status_code == 200
        assert {n["id"] for n in response.json()["nodes"]} == {"mine"}
        assert "private_other" not in response.text
    finally:
        db.select(other_graph).delete()


def test_qa_graph_feed_allowlist_and_no_store(workspace):
    db, tenant, graph, _, client, headers = workspace
    private_hash = "ab" * 32
    record_source(db, graph, tenant, id="source", kind="file", content_hash=private_hash)
    remember(db, graph, tenant, id="memory", text="PRIVATE MEMORY CONTENT", derived_from=["source"])
    response = client.get("/v1/graph/view", headers=headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    fields = {"id", "type", "status", "kind", "title", "uri", "tool", "low_integrity"}
    assert all(set(n) == fields for n in data["nodes"])
    assert all(set(t) == {"op", "ms", "rows"} for t in data["trace"])
    assert private_hash not in response.text and "PRIVATE MEMORY CONTENT" not in response.text
    assert headers["Authorization"].removeprefix("Bearer ") not in response.text


def test_qa_revoked_token_cannot_read_graph(workspace):
    _, tenant, _, registry, client, headers = workspace
    assert client.get("/v1/graph/view", headers=headers).status_code == 200
    registry.revoke_tenant(tenant)
    assert client.get("/v1/graph/view", headers=headers).status_code in {401, 403}
    assert client.get("/v1/graph/view?token=invalid").status_code == 401


def test_qa_closed_edge_projection_and_read_only(workspace):
    db, tenant, graph, _, client, headers = workspace
    record_source(db, graph, tenant, id="first", kind="file", now=1)
    record_source(db, graph, tenant, id="second", kind="file", now=2)
    remember(db, graph, tenant, id="third", derived_from=["first"], now=3)
    corroborate(db, graph, "third", "second", by="human")
    before = db.ro_query(graph, "MATCH (n) RETURN n.id, properties(n) ORDER BY n.id").result_set
    full = client.get("/v1/graph/view", headers=headers).json()
    assert {e["type"] for e in full["edges"]} == {"DERIVED_FROM", "CORROBORATED_BY"}
    bounded = client.get("/v1/graph/view?limit=2", headers=headers).json()
    assert bounded["truncated"] is True
    assert {n["id"] for n in bounded["nodes"]} == {"first", "second"}
    assert bounded["edges"] == []
    assert db.ro_query(graph, "MATCH (n) RETURN n.id, properties(n) ORDER BY n.id").result_set == before


def test_qa_static_root_cannot_serve_local_private_files(workspace):
    *_, client, _headers = workspace
    for path in ("/scratch/demo-demo.json", "/.env", "/src/pedigree/config.py", "/%2e%2e/%2e%2e/.env"):
        assert client.get(path).status_code == 404
    script = client.get("/app.js")
    assert script.status_code == 200
    assert "textContent" in script.text
    for unsafe in ("innerHTML", "insertAdjacentHTML", "localStorage", "sessionStorage", "console.log"):
        assert unsafe not in script.text
    html = client.get("/").text
    assert "https://" not in html and "http://" not in html


@pytest.mark.parametrize("limit", ["-1", "1.5", "x') DELETE n //", "1000000"])
def test_qa_graph_invalid_limits_rejected(workspace, limit):
    *_, client, headers = workspace
    assert client.get("/v1/graph/view", params={"limit": limit}, headers=headers).status_code == 422
