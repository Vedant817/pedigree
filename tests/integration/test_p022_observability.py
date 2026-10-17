"""P-022: response trace, metric families and the JSON access log - no credential leakage."""
import asyncio
import json
import logging

import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings
from pedigree.engine.ingest import record_source
from pedigree.mcp_server import build_mcp

ADMIN_TOKEN = "p022-fixture-admin"
TOKEN_SHAPES = ("ped_a_", "ped_o_")


def _run(coro):
    return asyncio.run(coro)


def _series_value(body: str, line_prefix: str) -> float:
    for line in body.splitlines():
        if line.startswith(line_prefix + "{") or line.startswith(line_prefix + " "):
            return float(line.rsplit(" ", 1)[1])
    return 0.0


def _trace_ok(entries):
    assert isinstance(entries, list) and entries, "trace must be a non-empty list"
    for entry in entries:
        assert set(entry) == {"op", "ms", "rows"}
        assert isinstance(entry["op"], str) and entry["op"]
        assert entry["ms"] >= 0 and entry["rows"] >= 0
    assert not any(shape in json.dumps(entries) for shape in TOKEN_SHAPES)


@pytest.fixture
def boundary(fresh_graph):
    db, tenant, graph = fresh_graph
    settings = Settings(pedigree_admin_token=ADMIN_TOKEN)
    registry = TenantRegistry(db, settings)
    credential = registry.create_tenant(tenant)
    record_source(db, graph, tenant, id="p022-src", kind="web", uri="local-p022")
    try:
        with TestClient(create_app(db, settings), raise_server_exceptions=False) as client:
            yield {
                "db": db,
                "graph": graph,
                "tenant": tenant,
                "client": client,
                "operator": {"Authorization": "Bearer " + credential.operator_token},
                "agent": {"Authorization": "Bearer " + credential.agent_token},
                "admin": {"x-admin-token": ADMIN_TOKEN},
            }
    finally:
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})


def test_rest_responses_carry_the_action_trace(boundary):
    client = boundary["client"]
    revoke = client.post("/v1/revoke", headers=boundary["operator"],
                         json={"root_id": "p022-src", "reason": "trace check"})
    assert revoke.status_code == 200, revoke.text
    _trace_ok(revoke.json()["trace"])

    blame = client.get("/v1/blame/p022-src", headers=boundary["agent"])
    assert blame.status_code == 200, blame.text
    _trace_ok(blame.json()["trace"])

    impact = client.get("/v1/impact/p022-src", headers=boundary["agent"])
    assert impact.status_code == 200, impact.text
    _trace_ok(impact.json()["trace"])

    gate = client.post("/v1/gate", headers=boundary["agent"],
                       json={"action": {"tool": "read_file", "summary": "trace check"},
                             "relied_on": ["p022-src"]})
    assert gate.status_code == 200, gate.text
    _trace_ok(gate.json()["trace"])
    assert gate.json()["decision"] in ("allow", "warn", "reverify", "block")


def test_metrics_series_exist_and_move_with_the_action(boundary):
    client = boundary["client"]
    tenant = boundary["tenant"]
    before = client.get("/metrics", headers=boundary["admin"])
    assert before.status_code == 200, before.text
    revokes_before = _series_value(before.text, 'pedigree_revocations_total{status="done"}')
    assert "# TYPE pedigree_query_seconds histogram" in before.text

    revoke = client.post("/v1/revoke", headers=boundary["operator"],
                         json={"root_id": "p022-src", "reason": "metrics check"})
    assert revoke.status_code == 200, revoke.text

    gate = client.post("/v1/gate", headers=boundary["agent"],
                       json={"action": {"tool": "read_file", "summary": "metrics check"},
                             "relied_on": ["p022-src"]})
    assert gate.status_code == 200, gate.text
    decision = gate.json()["decision"]

    stats = client.get("/v1/stats", headers=boundary["agent"])
    assert stats.status_code == 200, stats.text
    after = client.get("/metrics", headers=boundary["admin"])
    assert after.status_code == 200, after.text

    revokes_after = _series_value(after.text, 'pedigree_revocations_total{status="done"}')
    assert revokes_after == revokes_before + 1
    assert _series_value(after.text,
                         f'pedigree_gate_decisions_total{{decision="{decision}"}}') >= 1
    assert 'pedigree_query_seconds_count{' in after.text
    assert any("pedigree_nodes{" in line and 'status="revoked"' in line
               and f'tenant="{tenant}"' in line for line in after.text.splitlines())


def test_access_log_is_json_without_credentials(boundary, caplog):
    token = boundary["operator"]["Authorization"].split(" ", 1)[1]
    with caplog.at_level(logging.INFO, logger="pedigree.access"):
        response = boundary["client"].get("/v1/stats", headers=boundary["operator"])
    assert response.status_code == 200, response.text
    lines = [record.getMessage() for record in caplog.records if record.name == "pedigree.access"]
    assert lines, "one access line per request"
    line = lines[-1]
    record = json.loads(line)
    assert record["status"] == 200
    assert record["path"] == "/v1/stats"
    assert record["method"] == "GET"
    assert record["tenant"] == boundary["tenant"]
    assert record["op"] == "read"
    assert record["request_id"] == response.headers["x-correlation-id"]
    assert isinstance(record["ms"], (int, float))
    assert token not in line
    assert not any(shape in line for shape in TOKEN_SHAPES)


def test_mcp_tools_carry_the_action_trace(fresh_graph):
    db, tenant, graph = fresh_graph
    settings = Settings(pedigree_admin_token=ADMIN_TOKEN)
    registry = TenantRegistry(db, settings)
    credential = registry.create_tenant(tenant)
    server = build_mcp(db, settings, tenant, credential.operator_token).server

    async def invoke(name, args):
        result = await server.call_tool(name, args)
        return json.loads(result.content[0].text)

    common = {"tenant_id": tenant, "token": credential.operator_token}
    try:
        seeded = _run(invoke("pedigree_record_source", {**common, "kind": "web", "uri": "local-p022-mcp"}))
        assert seeded["ok"] is True, seeded
        source_id = seeded["result"]["id"]

        revoked = _run(invoke("pedigree_revoke", {**common, "root_id": source_id, "reason": "mcp trace"}))
        assert revoked["ok"] is True, revoked
        _trace_ok(revoked["result"]["trace"])

        blamed = _run(invoke("pedigree_blame", {**common, "node_id": source_id}))
        assert blamed["ok"] is True, blamed
        _trace_ok(blamed["result"]["trace"])

        impacted = _run(invoke("pedigree_impact", {**common, "node_id": source_id}))
        assert impacted["ok"] is True, impacted
        _trace_ok(impacted["result"]["trace"])

        gated = _run(invoke("pedigree_check_action",
                            {"token": credential.operator_token, "tool": "read_file",
                             "summary": "mcp trace", "relied_on": [source_id]}))
        assert gated["ok"] is True, gated
        _trace_ok(gated["result"]["trace"])
    finally:
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})
