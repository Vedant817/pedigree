"""Independent P-020 QA: real indexed authority and transport admission."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import httpx2
import pytest
import uvicorn
from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings, get_settings
from pedigree.db import queries as Q
from pedigree.db.schema import ensure_schema
from pedigree.errors import RateLimited
from pedigree.rate_limit import RateLimiter


@pytest.fixture
def registry(db):
    name = "qap020_" + uuid.uuid4().hex
    ensure_schema(db, name, label="Tenant")
    instance = object.__new__(TenantRegistry)
    instance.db, instance.settings, instance.gname = db, get_settings(), name
    try:
        yield instance
    finally:
        db.select(name).delete()
        assert name not in db.list_graphs()


def test_independent_indexed_hit_miss_nullable_legacy_and_ambiguity(registry, monkeypatch):
    credentials = registry.create_tenant("independent")
    rows = [{"id": "qa" + str(index), "sha": hashlib.sha256(str(index).encode()).hexdigest()}
            for index in range(257)]
    registry.db.query(registry.gname, """UNWIND $rows AS row CREATE(:Tenant {
        id:row.id,agent_token_sha256:row.sha,status:'active',node_cap:100,created_at:1})""", {"rows": rows})
    plan = str(registry.db.select(registry.gname).explain(Q.Q_REGISTRY_BY_DIGEST, {"sha": "absent"}))
    assert "Node By Index Scan" in plan and "Label Scan" not in plan
    calls = []
    original = registry.db.ro_query

    def observe(graph, query, *args, **kwargs):
        if graph == registry.gname:
            calls.append(query)
        return original(graph, query, *args, **kwargs)

    monkeypatch.setattr(registry.db, "ro_query", observe)
    for supplied, expected in [(credentials.agent_token, "agent"),
                               (credentials.operator_token, "operator"), ("ped_a_absent_qa", None)]:
        calls.clear()
        principal = registry.resolve(supplied)
        assert (principal.role if principal else None) == expected
        assert calls == [Q.Q_REGISTRY_BY_DIGEST]
    old = "ped_legacy_qa-only-synthetic"
    registry.db.query(registry.gname, """CREATE(:Tenant {id:'legacy',status:'active',
        node_cap:100,created_at:1,token_sha256:$sha})""", {"sha": hashlib.sha256(old.encode()).hexdigest()})
    assert registry.resolve(old).role == "agent"
    registry.db.query(registry.gname, """CREATE(:Tenant {id:'collision',status:'active',
        node_cap:100,created_at:1,operator_token_sha256:$sha})""",
        {"sha": hashlib.sha256(credentials.agent_token.encode()).hexdigest()})
    assert registry.resolve(credentials.agent_token) is None


def test_cross_process_rotation_and_status_take_effect_without_cache_invalidation(registry):
    credentials = registry.create_tenant("rotation")
    assert registry.resolve(credentials.operator_token).role == "operator"
    script = """
import json,sys
from pedigree.api.registry import TenantRegistry
from pedigree.config import get_settings
from pedigree.db.client import Db
data=json.load(sys.stdin)
registry=object.__new__(TenantRegistry)
registry.db,registry.settings,registry.gname=Db(),get_settings(),data['graph']
if data['operation']=='rotate':
    new=registry.issue_operator('rotation',rotate=True)
    ok=registry.resolve(new).role=='operator' and registry.resolve(data['old']) is None
else:
    registry.revoke_tenant('rotation')
    ok=registry.resolve(data['agent']) is None
print(json.dumps({'ok':ok}))
"""
    for operation in ("rotate", "revoke"):
        process = subprocess.run([sys.executable, "-c", script], input=json.dumps({
            "graph": registry.gname, "operation": operation, "old": credentials.operator_token,
            "agent": credentials.agent_token}), text=True, capture_output=True, timeout=20)
        assert process.returncode == 0, "cross-process registry probe failed"
        assert json.loads(process.stdout) == {"ok": True}
        assert registry.resolve(credentials.operator_token) is None
        assert (registry.resolve(credentials.agent_token) is None) == (operation == "revoke")


def test_atomic_destructive_rejection_and_separate_budgets():
    limiter = RateLimiter(clock=lambda: 0, read_limit=2, write_limit=2, destructive_limit=1)
    limiter.admit("qa", "revoke", dry_run=True)
    with pytest.raises(RateLimited):
        limiter.admit("qa", "reinstate")
    # A rejected dual-budget reservation must not spend the unblocked write bucket.
    limiter.admit("qa", "write")
    limiter.admit("qa", "write")
    limiter.admit("qa", "read")
    with pytest.raises(RateLimited):
        limiter.admit("qa", "read")


def test_concurrent_capacity_is_bounded_and_never_resets_exhausted_keys():
    now = [0.0]
    limiter = RateLimiter(clock=lambda: now[0], write_limit=3, max_keys=2)

    def attempt(tenant):
        try:
            limiter.admit(tenant, "write")
            return True
        except RateLimited:
            return False

    with ThreadPoolExecutor(max_workers=12) as pool:
        assert sum(pool.map(attempt, ["one"] * 40)) == 3
        assert sum(pool.map(attempt, ["two"] * 40)) == 3
        assert not any(pool.map(attempt, ["extra" + str(i) for i in range(40)]))
    assert len(limiter._buckets) == 2
    assert all(len(samples) == 3 for samples in limiter._buckets.values())
    assert not attempt("one")
    now[0] = 60
    assert attempt("new")
    assert len(limiter._buckets) == 1


@contextmanager
def live(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, proxy_headers=False, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()


@pytest.fixture
def service(fresh_graph, monkeypatch):
    db, tenant, graph = fresh_graph
    monkeypatch.setattr("pedigree.api.app._startup_resume", lambda *args: None)
    now = [0.0]
    limiter = RateLimiter(clock=lambda: now[0], write_limit=2, read_limit=2)
    app = create_app(db, Settings(_env_file=None, pedigree_admin_token="qa-local-admin"), limiter=limiter)
    credentials = app.state.registry.create_tenant(tenant)
    try:
        with live(app) as base:
            yield db, graph, base, credentials, limiter, now
    finally:
        db.query(app.state.registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})


def bearer(token):
    return {"Authorization": "Bearer " + token}


def mcp_call(base, tool, arguments=None, headers=None):
    async def call():
        async with httpx2.AsyncClient(headers=headers or {}) as transport:
            async with Client(streamable_http_client(base + "/mcp", http_client=transport)) as client:
                result = await client.call_tool(tool, arguments or {})
                return json.loads(result.content[0].text)
    return asyncio.run(call())


def test_actual_tcp_rest_and_mounted_mcp_share_role_budgets(service):
    db, graph, base, credentials, _, _ = service
    with httpx2.Client() as client:
        assert client.post(base + "/v1/sources", headers=bearer(credentials.agent_token),
                           json={"kind": "web", "id": "rest"}).status_code == 200
        result = mcp_call(base, "pedigree_record_source", {"id": "mcp"}, bearer(credentials.operator_token))
        assert result.get("ok") is True
        response = client.post(base + "/v1/sources", headers=bearer(credentials.operator_token),
                               json={"kind": "web", "id": "blocked"})
        assert response.status_code == 429 and response.headers["Retry-After"] == "60"
        assert client.get(base + "/v1/stats", headers=bearer(credentials.agent_token)).status_code == 200
        assert mcp_call(base, "pedigree_report", headers=bearer(credentials.operator_token))["ok"]
        assert client.get(base + "/v1/stats", headers=bearer(credentials.agent_token)).status_code == 429
    assert db.ro_query(graph, "MATCH(n) RETURN count(n)").result_set == [[2]]


def test_actual_tcp_failed_auth_rest_mcp_peer_shared_spoof_ignored_and_expires(service):
    _, _, base, credentials, _, now = service
    with httpx2.Client() as client:
        for index in range(10):
            response = client.get(base + "/v1/stats", headers={
                "Authorization": "Bearer invalid", "X-Forwarded-For": f"198.51.100.{index}",
                "Forwarded": f"for=203.0.113.{index}"})
            assert response.status_code == 401
        result = mcp_call(base, "pedigree_report", headers={**bearer(credentials.agent_token),
            "X-Forwarded-For": "192.0.2.99", "Forwarded": "for=192.0.2.99"})
        assert result["error"]["code"] == "rate_limited"
        assert result["error"]["detail"]["retry_after"] == 60
        assert client.get(base + "/v1/stats", headers=bearer(credentials.operator_token)).status_code == 429
        now[0] = 60
        assert mcp_call(base, "pedigree_report", headers=bearer(credentials.agent_token))["ok"]
        assert client.get(base + "/v1/stats", headers=bearer(credentials.operator_token)).status_code == 200


def test_actual_tcp_recorded_gate_write_and_read_gate_are_distinct(service):
    _, _, base, credentials, limiter, _ = service
    limiter.read_limit = limiter.write_limit = 1
    with httpx2.Client() as client:
        assert client.post(base + "/v1/gate", headers=bearer(credentials.agent_token),
                           json={"action": {"tool": "Read"}, "record": False}).status_code == 200
        assert mcp_call(base, "pedigree_report", headers=bearer(credentials.agent_token))["error"]["code"] == "rate_limited"
        result = mcp_call(base, "pedigree_check_action", {"tool": "cat", "record": True}, bearer(credentials.agent_token))
        assert result["ok"]
        assert client.post(base + "/v1/whatif", headers=bearer(credentials.agent_token),
                           json={"roots": ["missing"]}).status_code == 429


@pytest.mark.parametrize("dry_run", [False, True])
def test_actual_tcp_destructive_reservation_atomic_across_rest_mcp(service, dry_run):
    _, _, base, credentials, limiter, now = service
    with httpx2.Client() as client:
        assert client.post(base + "/v1/sources", headers=bearer(credentials.agent_token),
                           json={"kind": "web", "id": "root"}).status_code == 200
        now[0] = 60
        limiter.destructive_limit = 1
        response = client.post(base + "/v1/revoke", headers=bearer(credentials.operator_token),
                               json={"root_id": "root", "dry_run": dry_run})
        assert response.status_code == 200
        rejected = mcp_call(base, "pedigree_reinstate", {"root_id": "root", "dry_run": not dry_run},
                            bearer(credentials.operator_token))
        assert rejected["error"]["code"] == "rate_limited"
        # The opposite budget remains fully available after failed reservation.
        if dry_run:
            for node in ("one", "two"):
                assert mcp_call(base, "pedigree_record_source", {"id": node}, bearer(credentials.agent_token))["ok"]
            assert mcp_call(base, "pedigree_record_source", {"id": "blocked"}, bearer(credentials.agent_token))["error"]["code"] == "rate_limited"
            assert client.get(base + "/v1/stats", headers=bearer(credentials.agent_token)).status_code == 200
            assert client.get(base + "/v1/stats", headers=bearer(credentials.agent_token)).status_code == 429
        else:
            for _ in range(2):
                assert client.get(base + "/v1/stats", headers=bearer(credentials.agent_token)).status_code == 200
            assert client.get(base + "/v1/stats", headers=bearer(credentials.agent_token)).status_code == 429
            assert mcp_call(base, "pedigree_record_source", {"id": "one"}, bearer(credentials.agent_token))["ok"]
            assert mcp_call(base, "pedigree_record_source", {"id": "blocked"}, bearer(credentials.agent_token))["error"]["code"] == "rate_limited"


def test_shipped_cli_stdio_backoff_is_server_local_and_blocks_valid_default(fresh_graph):
    db, tenant, _ = fresh_graph
    registry = TenantRegistry(db)
    credentials = registry.create_tenant(tenant)
    environment = {**os.environ, "PEDIGREE_MCP_TENANT": tenant,
                   "PEDIGREE_MCP_TOKEN": credentials.agent_token}
    parameters = StdioServerParameters(command=sys.executable,
        args=["-m", "pedigree.cli", "mcp", "--transport", "stdio"], env=environment)

    async def journey():
        async with Client(parameters) as client:
            for index in range(10):
                result = await client.call_tool("pedigree_report", {
                    "token": "invalid" + str(index), "tenant_id": "spoof" + str(index)})
                assert json.loads(result.content[0].text)["error"]["code"] == "unauthorized"
            result = await client.call_tool("pedigree_report", {})
            payload = json.loads(result.content[0].text)
            assert payload["error"]["code"] == "rate_limited"
            assert 1 <= payload["error"]["detail"]["retry_after"] <= 60

    try:
        asyncio.run(journey())
    finally:
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})
