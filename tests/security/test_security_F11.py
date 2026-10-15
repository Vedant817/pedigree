"""F-11 trust boundary regressions using isolated real FalkorDB tenants."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings
from pedigree.engine.ingest import corroborate, ensure_session, record_source, remember, session_read
from pedigree.engine.revoke import revoke
from pedigree.mcp_server import build_mcp


@pytest.fixture
def boundary(fresh_graph):
    db, tenant, graph = fresh_graph
    settings = Settings(pedigree_admin_token="synthetic-admin", pedigree_policy_file="missing-policy.yaml")
    registry = TenantRegistry(db, settings)
    cred = registry.create_tenant(tenant)
    client = TestClient(create_app(db, settings))
    headers = {"Authorization": "Bearer " + cred.token}
    try:
        yield db, tenant, graph, settings, cred.token, client, headers
    finally:
        db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": tenant})


def test_laundering_default_author_is_agent(boundary):
    db, tenant, graph, _, _, client, headers = boundary
    record_source(db, graph, tenant, id="rules", kind="rules_file")
    record_source(db, graph, tenant, id="fake", kind="file")
    remember(db, graph, tenant, id="belief", derived_from=["rules"])
    response = client.post("/v1/corroborate", headers=headers,
                           json={"memory_id": "belief", "source_id": "fake"})
    assert response.status_code == 200, response.text
    revoke(db, graph, tenant, root_id="rules")
    response = client.post("/v1/gate", headers=headers,
                           json={"action": {"tool": "Bash", "summary": "git commit -m x"}, "relied_on": ["belief"]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["decision"] == "block"
    assert result["hook"]["hookSpecificOutput"]["permissionDecision"] == "deny"
    # Engine default is also agent, never implicit human attestation.
    corroborate(db, graph, "belief", "fake")
    row = db.ro_query(graph, "MATCH ()-[c:CORROBORATED_BY]->() RETURN c.by").result_set[0]
    assert row == ["agent"]


@pytest.mark.parametrize("extra", [{"policy_path": "C:/Windows/win.ini"}, {"tenant": "other"},
                                   {"relied_on": ["x"] * 65},
                                   {"action": {"tool": "Edit", "audience": ["x"] * 9}}])
def test_request_rejects_unsafe_fields_and_limits(boundary, extra):
    *_, client, headers = boundary
    response = client.post("/v1/gate", headers=headers, json={"action": {"tool": "Edit"}, **extra})
    assert response.status_code == 422


def test_read_window_cannot_silently_clear_taint(boundary):
    db, tenant, graph, _, _, client, headers = boundary
    record_source(db, graph, tenant, id="src", kind="file")
    ensure_session(db, graph, tenant, "session")
    session_read(db, graph, "session", "src")
    revoke(db, graph, tenant, root_id="src")
    r = client.post("/v1/gate", headers=headers,
                    json={"action": {"tool": "Read"}, "session_id": "session", "relied_on": []})
    assert r.json()["decision"] == "reverify", r.text


def test_auth_unknown_and_id_injection(boundary):
    *_, client, headers = boundary
    body = {"action": {"tool": "Bash", "summary": "git push"}, "relied_on": ["ghost"]}
    assert client.post("/v1/gate", json=body).status_code == 401
    r = client.post("/v1/gate", headers=headers, json=body)
    assert r.status_code == 200 and r.json()["decision"] == "reverify"
    body["relied_on"] = ["x') DELETE n //"]
    assert client.post("/v1/gate", headers=headers, json=body).status_code == 422


def test_mcp_gate_and_corroboration_contract(boundary):
    db, tenant, _, settings, token, _, _ = boundary
    server = build_mcp(db, settings).server

    async def run():
        tools = {t.name: t for t in await server.list_tools()}
        schema = tools["pedigree_check_action"].input_schema
        assert "policy_path" not in schema["properties"]
        assert tools["pedigree_corroborate"].input_schema["properties"]["by"]["default"] == "agent"
        response = await server.call_tool("pedigree_check_action", {
            "token": token, "tool": "Edit", "relied_on": ["ghost"]})
        result = json.loads(response.content[0].text)
        assert result["ok"] is True
        assert result["result"]["decision"] == "reverify"
        response = await server.call_tool("pedigree_check_action", {"tool": "Edit"})
        assert json.loads(response.content[0].text)["ok"] is False
    asyncio.run(run())
