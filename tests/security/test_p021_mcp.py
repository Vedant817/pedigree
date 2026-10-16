"""MCP argument/auth failures must be typed and never reflect caller secrets."""
import asyncio
import json

import pytest

from pedigree.api.registry import TenantRegistry
from pedigree.mcp_server import build_mcp

CANARY = "private-probe-must-never-be-reflected"


@pytest.fixture
def boundary(fresh_graph):
    db, tenant, graph = fresh_graph
    registry = TenantRegistry(db)
    credentials = registry.create_tenant(tenant)
    server = build_mcp(db, default_tenant_id=tenant, default_tenant_token=credentials.token)
    try:
        yield server, db, graph
    finally:
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})


def invoke(server, name, args):
    result = asyncio.run(server.server.call_tool(name, args))
    return json.loads(result.content[0].text)


@pytest.mark.parametrize("name,args", [
    ("pedigree_record_source", {"conf": CANARY}),
    ("pedigree_record_source", {"unexpected": CANARY}),
    ("pedigree_remember", {"derived_from": CANARY}),
    ("pedigree_record_action", {"tool": "cat", "artifacts": 5}),
    ("pedigree_check_action", {"tool": "cat", "max_depth": True}),
    ("pedigree_record_source", {"uri": "file://a\x00b"}),
])
def test_malformed_tool_arguments_are_safe_before_writes(boundary, caplog, name, args):
    server, db, graph = boundary
    payload = invoke(server, name, args)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_argument"
    assert CANARY not in json.dumps(payload)
    assert CANARY not in caplog.text
    assert db.ro_query(graph, "MATCH(n) RETURN count(n)").result_set[0][0] == 0


@pytest.mark.parametrize("target", ["registry", "schema"])
def test_registry_fault_is_contained_before_tool_body(boundary, monkeypatch, caplog, target):
    server, *_ = boundary

    def fail(*args, **kwargs):
        raise RuntimeError(CANARY)

    if target == "registry":
        monkeypatch.setattr(server.registry, "resolve", fail)
    else:
        monkeypatch.setattr("pedigree.mcp_server.ensure_schema", fail)
    payload = invoke(server, "pedigree_report", {})
    assert payload["error"]["code"] == "internal"
    assert payload["error"]["correlation_id"]
    assert CANARY not in json.dumps(payload)
    assert CANARY not in caplog.text


def test_engine_fault_inside_call_is_safe(boundary, monkeypatch, caplog):
    server, *_ = boundary

    def fail(*args, **kwargs):
        raise RuntimeError(CANARY)

    monkeypatch.setattr("pedigree.mcp_server.record_source", fail)
    payload = invoke(server, "pedigree_record_source", {"kind": "web", "uri": "file://safe"})
    assert payload["error"]["code"] == "internal"
    assert payload["error"]["correlation_id"]
    assert CANARY not in json.dumps(payload)
    assert CANARY not in caplog.text


def test_unknown_tool_name_is_not_reflected(boundary, caplog):
    payload = invoke(boundary[0], CANARY, {})
    assert payload["error"]["code"] == "invalid_argument"
    assert CANARY not in json.dumps(payload)
    assert CANARY not in caplog.text
