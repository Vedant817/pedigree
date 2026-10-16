"""Authenticated capture authority must come from a server credential, not payload claims."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings
from pedigree.engine.ingest import corroborate, record_source, remember
from pedigree.mcp_server import build_mcp


@pytest.fixture
def capture_boundary(fresh_graph):
    db, tenant, graph = fresh_graph
    settings = Settings(pedigree_admin_token="capture-test-operator")
    registry = TenantRegistry(db, settings)
    credential = registry.create_tenant(tenant)
    client_operator_token = credential.operator_token
    headers = {"Authorization": "Bearer " + credential.token}
    with TestClient(create_app(db, settings)) as client:
        client.p015_operator_token = client_operator_token
        try:
            yield db, tenant, graph, settings, credential.token, client, headers
        finally:
            db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": tenant})


def seed_support(boundary):
    db, tenant, graph, *_ = boundary
    record_source(db, graph, tenant, id="support", kind="human")
    remember(db, graph, tenant, id="belief", text="unverified claim")


@pytest.mark.parametrize("author", ["human", "scanner"])
@pytest.mark.parametrize("admin", [None, "incorrect-operator", "capture-test-operator"])
def test_tenant_cannot_assert_trusted_corroboration(capture_boundary, author, admin):
    seed_support(capture_boundary)
    db, _, graph, _, _, client, headers = capture_boundary
    if admin:
        headers = {**headers, "X-Admin-Token": admin}
    response = client.post("/v1/corroborate", headers=headers,
                           json={"memory_id": "belief", "source_id": "support", "by": author})
    assert response.status_code in (401, 403), response.text
    assert db.ro_query(graph, "MATCH ()-[c:CORROBORATED_BY]->() RETURN c.by").result_set == []


@pytest.mark.parametrize("author", ["human", "scanner"])
def test_operator_credential_can_attest_with_tenant_scope(capture_boundary, author):
    seed_support(capture_boundary)
    db, _, graph, _, _, client, _ = capture_boundary
    response = client.post("/v1/corroborate",
                           headers={"Authorization": "Bearer " + client.p015_operator_token},
                           json={"memory_id": "belief", "source_id": "support", "by": author})
    assert response.status_code == 200, response.text
    assert db.ro_query(graph, "MATCH ()-[c:CORROBORATED_BY]->() RETURN c.by").result_set == [[author]]


@pytest.mark.parametrize("kind", ["web", "human", "file", "rules_file"])
def test_rest_kind_and_integrity_claims_are_not_credentials(capture_boundary, kind):
    _, _, _, _, _, client, headers = capture_boundary
    response = client.post("/v1/sources", headers=headers,
                           json={"kind": kind, "integrity": "trusted", "uri": "file:///unverified"})
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("kind", ["human", "file"])
def test_runtime_string_does_not_authorize_capture(capture_boundary, kind):
    db, _, graph, _, _, client, headers = capture_boundary
    response = client.post("/v1/events", headers=headers, json={"runtime": "claude-code", "events": [
        {"type": "source", "kind": kind, "integrity": "trusted", "uri": "file:///claimed", "content_hash": "a" * 64}]})
    assert response.status_code in (200, 401, 403), response.text
    rows = db.ro_query(graph, "MATCH (s:Source) RETURN s.low_integrity").result_set
    assert all(row == [True] for row in rows), rows


def test_agent_cannot_overwrite_existing_human_attestation(capture_boundary):
    seed_support(capture_boundary)
    db, _, graph, _, _, client, headers = capture_boundary
    corroborate(db, graph, "belief", "support", by="human")
    response = client.post("/v1/corroborate", headers=headers,
                           json={"memory_id": "belief", "source_id": "support", "by": "agent"})
    assert response.status_code == 200, response.text
    assert db.ro_query(graph, "MATCH ()-[c:CORROBORATED_BY]->() RETURN c.by").result_set == [["human"]]


@pytest.mark.parametrize("operation", ["human", "scanner", "source-human", "source-file", "source-trusted"])
def test_mcp_payload_cannot_mint_authority(capture_boundary, operation):
    seed_support(capture_boundary)
    db, _, graph, settings, token, _, _ = capture_boundary
    server = build_mcp(db, settings).server

    async def run():
        tools = {tool.name: tool for tool in await server.list_tools()}
        for name in ("pedigree_corroborate", "pedigree_record_source"):
            assert "admin_token" not in tools[name].input_schema["properties"]
        if operation.startswith("source-"):
            kind = operation.removeprefix("source-")
            args = {"token": token, "kind": "web" if kind == "trusted" else kind,
                    "uri": "file:///mcp-claim", "integrity": "trusted"}
            response = await server.call_tool("pedigree_record_source", args)
            result = json.loads(response.content[0].text)
            assert result.get("ok") is False, result
            assert result["error"]["code"] == "forbidden"
        else:
            response = await server.call_tool("pedigree_corroborate", {
                "token": token, "memory_id": "belief", "source_id": "support", "by": operation})
            result = json.loads(response.content[0].text)
            assert result.get("ok") is False, result
            assert result["error"]["code"] == "forbidden"
            assert db.ro_query(graph, "MATCH ()-[c:CORROBORATED_BY]->() RETURN c.by").result_set == []
    asyncio.run(run())
