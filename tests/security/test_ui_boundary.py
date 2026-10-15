"""F-09 normal trust-boundary regressions; real DB, no browser claims."""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings, graph_name
from pedigree.db.schema import ensure_schema
from pedigree.engine.ingest import record_action, record_source, remember


@pytest.fixture
def workspace(fresh_graph):
    db, tenant, graph = fresh_graph
    other = "u" + uuid.uuid4().hex[:10]
    other_graph = graph_name(other)
    ensure_schema(db, other_graph)
    settings = Settings(_env_file=None, pedigree_admin_token="synthetic-admin-ui-test",
                        pedigree_secret="synthetic-secret-ui-test", gemini_api_key="", groq_api_key="")
    registry = TenantRegistry(db, settings)
    first = registry.create_tenant(tenant)
    second = registry.create_tenant(other)
    client = TestClient(create_app(db, settings))
    record_source(db, graph, tenant, id="own_source", kind="file", title="Own source")
    remember(db, graph, tenant, id="own_memory", text="private memory boundary marker", derived_from=["own_source"])
    record_action(db, graph, tenant, id="own_action", tool="Bash", summary="private summary boundary marker", relied_on=["own_memory"])
    record_source(db, other_graph, other, id="other_source", kind="file", title="Other tenant source")
    try:
        yield client, first.token, second.token, settings
    finally:
        db.select(other_graph).delete()
        for tid in (tenant, other):
            db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": tid})


def fetch(workspace, query="", token=None, headers=None):
    client, own, *_ = workspace
    return client.get("/v1/graph/view" + query,
                      headers={"Authorization": "Bearer " + (token or own), **(headers or {})})


def test_two_tenants_receive_only_their_persisted_nodes(workspace):
    first = fetch(workspace).json()
    second = fetch(workspace, token=workspace[2]).json()
    assert {node["id"] for node in first["nodes"]} == {"own_source", "own_memory", "own_action"}
    assert {node["id"] for node in second["nodes"]} == {"other_source"}
    assert "Other tenant source" not in str(first)


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid"}, {"Authorization": "Basic invalid"}])
def test_graph_auth_required(workspace, headers):
    response = workspace[0].get("/v1/graph/view", headers=headers)
    assert response.status_code == 401
    assert "own_source" not in response.text


@pytest.mark.parametrize("limit", ["0", "-1", "1001", "1000000", "abc", "1.5"])
def test_graph_bounds_reject_invalid_limit(workspace, limit):
    assert fetch(workspace, "?limit=" + limit).status_code == 422


@pytest.mark.parametrize("limit", [1, 2, 3, 1000])
def test_graph_projection_is_closed_and_truncation_truthful(workspace, limit):
    response = fetch(workspace, f"?limit={limit}")
    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) == min(3, limit)
    assert data["truncated"] is (limit < 3)
    ids = {node["id"] for node in data["nodes"]}
    assert all(edge["from"] in ids and edge["to"] in ids for edge in data["edges"])
    assert len(data["edges"]) <= 4000


def test_headers_and_query_do_not_override_token_tenant(workspace):
    response = fetch(workspace, "?tenant=other&graph_name=ped:other",
                     headers={"X-Tenant-ID": "other", "X-Graph-Name": "ped:other"})
    assert response.status_code == 200
    assert {node["id"] for node in response.json()["nodes"]} == {"own_source", "own_memory", "own_action"}


def test_projection_excludes_raw_memory_summary_and_credentials(workspace):
    response = fetch(workspace)
    assert response.headers["cache-control"] == "no-store"
    expected = {"id", "type", "status", "kind", "title", "uri", "tool", "low_integrity"}
    assert all(set(node) == expected for node in response.json()["nodes"])
    for value in ("private memory boundary marker", "private summary boundary marker",
                  workspace[1], workspace[2], workspace[3].pedigree_admin_token, workspace[3].pedigree_secret):
        assert value not in response.text


@pytest.mark.parametrize("path", ["/", "/app.js", "/style.css"])
def test_public_assets_do_not_embed_server_credentials(workspace, path):
    response = workspace[0].get(path)
    assert response.status_code == 200
    for value in (workspace[1], workspace[2], workspace[3].pedigree_admin_token, workspace[3].pedigree_secret):
        assert value not in response.text


def test_ui_source_uses_text_rendering_and_memory_only_token():
    source = (Path(__file__).resolve().parents[2] / "src/pedigree/ui/app.js").read_text(encoding="utf-8")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "localStorage", "sessionStorage", "console.log", "eval("):
        assert sink not in source
    assert "el.textContent = value" in source
    assert "redirect:'error'" in source and "cache:'no-store'" in source
    assert "epoch++" in source and "started !== epoch" in source
    assert "same(preview,snapshot())" in source
