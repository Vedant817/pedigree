"""Independent F-11 attacks against real isolated FalkorDB tenant graphs."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings, graph_name
from pedigree.db.schema import node_count
from pedigree.engine.gate import check_action
from pedigree.engine.ingest import record_source, remember
from pedigree.engine.revoke import revoke
from pedigree.mcp_server import build_mcp


@pytest.fixture
def target(fresh_graph):
    db, tenant, graph = fresh_graph
    settings = Settings(pedigree_admin_token="redteam-synthetic", pedigree_policy_file="missing.yaml")
    registry = TenantRegistry(db, settings)
    credential = registry.create_tenant(tenant)
    client = TestClient(create_app(db, settings), raise_server_exceptions=False)
    try:
        yield db, tenant, graph, settings, credential.token, client
    finally:
        db.query(graph_name("registry"), "MATCH (t:Tenant {id:$id}) DELETE t", {"id": tenant})


def post(target, **changes):
    body = {"action": {"tool": "Bash", "summary": "git push"}, **changes}
    return target[-1].post("/v1/gate", headers={"Authorization": "Bearer " + target[-2]}, json=body)


def mcp_call(target, **args):
    db, _, _, settings, token, _ = target
    server = build_mcp(db, settings).server

    async def run():
        response = await server.call_tool("pedigree_check_action", {"token": token, "tool": "Bash", **args})
        return json.loads(response.content[0].text)
    return asyncio.run(run())


def chain(target, length):
    db, tenant, graph, *_ = target
    record_source(db, graph, tenant, id="rules", kind="rules_file")
    record_source(db, graph, tenant, id="fake", kind="file")
    remember(db, graph, tenant, id="belief", derived_from=["rules"], corroborated_by=["fake"])
    parent = "belief"
    for i in range(length):
        child = f"dependent{i}"
        remember(db, graph, tenant, id=child, derived_from=[parent])
        parent = child
    revoke(db, graph, tenant, root_id="rules")
    return parent


@pytest.mark.parametrize("value", ["x') DELETE n //", "ｅvil", "x\n", "*"])
def test_gate_rejects_injection_and_lookalike_ids(target, value):
    response = post(target, relied_on=[value])
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("changes", [
    {"relied_on": ["x"] * 65},
    {"policy_path": "C:/Windows/win.ini"},
    {"tenant": "abc"},
    {"max_depth": 0},
    {"max_depth": 13},
    {"action": {"tool": "Edit", "audience": ["x"] * 9}},
    {"action": {"tool": "Edit", "summary": "x" * 301}},
])
def test_rest_limits_and_server_policy_boundary(target, changes):
    response = post(target, **changes)
    assert response.status_code == 422, response.text


def test_missing_dependency_is_reverify(target):
    response = post(target, relied_on=["missing"])
    assert response.status_code == 200 and response.json()["decision"] == "reverify", response.text


@pytest.mark.parametrize("length,depth", [(2, 1), (13, 12)])
def test_truncated_untrusted_support_never_silently_allows(target, length, depth):
    leaf = chain(target, length)
    response = post(target, relied_on=[leaf], max_depth=depth)
    print("TRUNCATION", length, depth, response.status_code, response.text)
    assert response.status_code == 200
    assert response.json()["decision"] != "allow", "Incomplete high-risk ancestry must reverify"


def test_record_missing_dependency_retains_reverify(target):
    response = post(target, relied_on=["missing"], record=True)
    print("RECORD_MISSING", response.status_code, response.text)
    assert response.status_code == 200, "Recording must not discard the gate verdict"
    assert response.json()["decision"] == "reverify"


def test_record_unknown_session_does_not_leave_partial_action(target):
    db, _, graph, *_ = target
    before = node_count(db, graph)
    response = post(target, session_id="nonexistent", record=True)
    after = node_count(db, graph)
    print("RECORD_SESSION", response.status_code, response.text, "node_delta", after - before)
    assert response.status_code == 200 or after == before, "An error must not silently persist an action"


def test_mcp_invalid_risk_is_rejected(target):
    result = mcp_call(target, risk="LOW", effect="irreversible", summary="git push")
    print("MCP_RISK", result)
    assert result["ok"] is False, "MCP must reject invalid risk just like REST"


def test_record_cap_blocks_write_but_keeps_read_available(target):
    db, tenant, graph, *_ = target
    db.query(graph_name("registry"), "MATCH (t:Tenant {id:$id}) SET t.node_cap=1", {"id": tenant})
    record_source(db, graph, tenant, id="source", kind="file")
    assert post(target, record=True).status_code == 429
    assert post(target).status_code == 200
    assert node_count(db, graph) == 1


def test_default_agent_support_blocks_direct_anchor(target):
    chain(target, 0)
    response = post(target, relied_on=["belief"])
    assert response.status_code == 200 and response.json()["decision"] == "block", response.text


def test_read_only_decision_does_not_write_graph(target):
    db, tenant, graph, *_ = target
    record_source(db, graph, tenant, id="source", kind="file")
    before = node_count(db, graph)
    result = check_action(db, graph, {"tool": "Bash", "summary": "git push"}, relied_on=["source"])
    assert result["decision"] == "allow" and node_count(db, graph) == before
