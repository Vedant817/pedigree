"""Independent P-020 hostile admission and authority probes against real DB."""
from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import httpx2
import pytest
import uvicorn
from fastapi.testclient import TestClient
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings, get_settings
from pedigree.db.queries import Q_REGISTRY_BY_DIGEST
from pedigree.db.schema import ensure_schema
from pedigree.errors import RateLimited
from pedigree.mcp_server import build_mcp
from pedigree.rate_limit import RateLimiter


def invoke(server, tool, arguments=None):
    result = asyncio.run(server.server.call_tool(tool, arguments or {}))
    return json.loads(result.content[0].text)


def bearer(token):
    return {"Authorization": "Bearer " + token}


@pytest.fixture
def service(fresh_graph, monkeypatch):
    db, tenant, graph = fresh_graph
    monkeypatch.setattr("pedigree.api.app._startup_resume", lambda *args: None)
    app = create_app(db, Settings(_env_file=None, pedigree_admin_token="attack-local-admin"))
    credentials = app.state.registry.create_tenant(tenant)
    server = build_mcp(db, default_tenant_id=tenant, default_tenant_token=credentials.agent_token,
                       limiter=app.state.limiter)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield db, tenant, graph, app, client, credentials, server
    finally:
        db.query(app.state.registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})


@pytest.fixture
def isolated_registry(db):
    name = "attackp020_" + uuid.uuid4().hex
    ensure_schema(db, name, label="Tenant")
    registry = object.__new__(TenantRegistry)
    registry.db, registry.settings, registry.gname = db, get_settings(), name
    try:
        yield registry
    finally:
        db.select(name).delete()
        assert name not in db.list_graphs()


def test_indexed_live_authority_prefix_corruption_and_nullable_slots(isolated_registry, monkeypatch):
    registry = isolated_registry
    credentials = registry.create_tenant("victim")
    queries = []
    original = registry.db.ro_query

    def record(graph, query, *args, **kwargs):
        if graph == registry.gname:
            queries.append(query)
        return original(graph, query, *args, **kwargs)

    monkeypatch.setattr(registry.db, "ro_query", record)
    assert registry.resolve(credentials.operator_token).role == "operator"
    registry.issue_operator("victim", rotate=True)
    assert registry.resolve(credentials.operator_token) is None
    assert registry.resolve(credentials.agent_token).role == "agent"
    registry.revoke_tenant("victim")
    assert registry.resolve(credentials.agent_token) is None
    # A stored digest in an operator slot is insufficient when its full prefix
    # belongs to a different tenant. Legacy role-looking tenant IDs stay agent.
    old = "ped_o_old_legacy-synthetic"
    registry.db.query(registry.gname, """CREATE(:Tenant {id:'o_old',status:'active',
        node_cap:1,created_at:1,token_sha256:$sha})""",
        {"sha": hashlib.sha256(old.encode()).hexdigest()})
    assert registry.resolve(old).role == "agent"
    registry.db.query(registry.gname, """CREATE(:Tenant {id:'alien',status:'active',
        node_cap:1,created_at:1,operator_token_sha256:$sha})""",
        {"sha": hashlib.sha256(credentials.operator_token.encode()).hexdigest()})
    assert registry.resolve(credentials.operator_token) is None
    # Duplicate digest candidates fail closed even when one textual prefix fits.
    registry.db.query(registry.gname, """CREATE(:Tenant {id:'collision',status:'active',
        node_cap:1,created_at:1,agent_token_sha256:$sha})""",
        {"sha": hashlib.sha256(old.encode()).hexdigest()})
    assert registry.resolve(old) is None
    assert set(queries) <= {Q_REGISTRY_BY_DIGEST,
        # Explicit management operations perform an ID read, never tenant scans.
        "MATCH (t:Tenant {id:$id}) RETURN t.id, t.status, t.node_cap, t.created_at, t.token_sha256, t.agent_token_sha256, t.operator_token_sha256"}
    plan = str(registry.db.select(registry.gname).explain(Q_REGISTRY_BY_DIGEST, {"sha": "absent"}))
    assert "Node By Index Scan" in plan and "Label Scan" not in plan


def test_parallel_auth_and_tenant_caps_remain_bounded_under_key_churn():
    now = [0.0]
    limiter = RateLimiter(clock=lambda: now[0], auth_limit=3, write_limit=2, max_keys=2)

    def failed(_):
        try:
            limiter.failed_auth("nat")
            return True
        except RateLimited:
            return False

    with ThreadPoolExecutor(max_workers=16) as pool:
        assert sum(pool.map(failed, range(48))) == 3
    limiter.admit("tenant", "write")
    limiter.admit("tenant", "write")
    for index in range(40):
        with pytest.raises(RateLimited):
            limiter.failed_auth("spoof" + str(index))
        with pytest.raises(RateLimited):
            limiter.admit("new" + str(index), "write")
    assert len(limiter._buckets) == 2
    assert sorted(map(len, limiter._buckets.values())) == [2, 3]
    with pytest.raises(RateLimited):
        limiter.check_peer("nat")
    with pytest.raises(RateLimited):
        limiter.admit("tenant", "write")
    now[0] = 60
    limiter.check_peer("nat")
    limiter.admit("new", "write")
    assert len(limiter._buckets) == 1


@pytest.mark.parametrize("dry_run", [False, True])
def test_rejected_dual_reservations_never_spend_or_create_other_bucket(dry_run):
    limiter = RateLimiter(read_limit=1, write_limit=1, destructive_limit=1, clock=lambda: 0)
    limiter.admit("victim", "revoke", dry_run=dry_run)
    with ThreadPoolExecutor(max_workers=12) as pool:
        def attempt(_):
            try:
                limiter.admit("victim", "reinstate", dry_run=not dry_run)
                return True
            except RateLimited:
                return False
        assert not any(pool.map(attempt, range(30)))
    other = "write" if dry_run else "read"
    assert ("tenant", "victim", other) not in limiter._buckets
    limiter.admit("victim", other)
    assert all(len(samples) == 1 for samples in limiter._buckets.values())


def test_every_tenant_read_route_and_tool_rejects_after_shared_budget(service):
    _, _, _, app, client, credentials, server = service
    app.state.limiter.read_limit = 1
    assert client.get("/v1/stats", headers=bearer(credentials.agent_token)).status_code == 200
    for path in ("/v1/stats", "/v1/graph", "/v1/graph/view", "/v1/audit/sources",
                 "/v1/blame/missing", "/v1/impact/missing", "/v1/invariants",
                 "/v1/artifacts/lookup?key=synthetic"):
        response = client.get(path, headers=bearer(credentials.operator_token))
        assert response.status_code == 429, path
        assert int(response.headers["Retry-After"]) > 0
    for tool, arguments in (("pedigree_report", {}), ("pedigree_blame", {"node_id": "missing"}),
            ("pedigree_impact", {"node_id": "missing"}), ("pedigree_audit_sources", {}),
            ("pedigree_check_action", {"tool": "Read"})):
        payload = invoke(server, tool, {**arguments, "token": credentials.operator_token})
        assert payload["error"]["code"] == "rate_limited", tool
    # Liveness and the public UI have no tenant identity or graph operation.
    assert client.get("/healthz").status_code == 200
    assert invoke(server, "pedigree_health")["ok"]


def test_every_tenant_writer_route_and_tool_rejects_after_shared_budget(service):
    db, _, graph, app, client, credentials, server = service
    app.state.limiter.write_limit = 1
    assert client.post("/v1/sources", headers=bearer(credentials.agent_token),
                       json={"kind": "web", "id": "root"}).status_code == 200
    routes = [("sources", {"kind": "web"}), ("memories", {}), ("actions", {"tool": "Read"}),
        ("corroborate", {"memory_id": "missing", "source_id": "root"}),
        ("sessions", {"session_id": "session"}),
        ("sessions/read", {"session_id": "session", "node_id": "root"}),
        ("events", {"events": []}), ("gate", {"action": {"tool": "Read"}, "record": True}),
        ("whatif", {"roots": ["root"]}), ("revoke", {"root_id": "root"}),
        ("reinstate", {"root_id": "root"})]
    for path, body in routes:
        response = client.post("/v1/" + path, headers=bearer(credentials.operator_token), json=body)
        assert response.status_code == 429, (path, response.status_code)
    for tool, arguments in (("pedigree_record_source", {}), ("pedigree_remember", {}),
        ("pedigree_record_action", {"tool": "Read"}),
        ("pedigree_corroborate", {"memory_id": "missing", "source_id": "root"}),
        ("pedigree_check_action", {"tool": "Read", "record": True}),
        ("pedigree_whatif", {"roots": ["root"]}), ("pedigree_revoke", {"root_id": "root"}),
        ("pedigree_reinstate", {"root_id": "root"})):
        result = invoke(server, tool, {**arguments, "token": credentials.operator_token})
        assert result["error"]["code"] == "rate_limited", tool
    assert db.ro_query(graph, "MATCH(n) RETURN count(n)").result_set == [[1]]


def test_auth_threshold_precedes_lookup_and_survives_missing_malformed_headers(service, monkeypatch):
    _, _, _, app, client, credentials, _ = service
    limiter = app.state.limiter
    limiter.auth_limit = 3
    now = [0.0]
    limiter.clock = lambda: now[0]
    calls = []
    original = app.state.registry.resolve

    def resolve(token):
        calls.append(True)
        return original(token)

    monkeypatch.setattr(app.state.registry, "resolve", resolve)
    for headers in ({}, {"Authorization": "Bearer  synthetic-private"},
                    {"Authorization": "Bearer invalid"}):
        assert client.get("/v1/stats", headers=headers).status_code == 401
    assert calls == [True]
    for index in range(5):
        response = client.get("/v1/stats", headers={**bearer(credentials.agent_token),
            "X-Forwarded-For": str(index), "Forwarded": "for=" + str(index)})
        assert response.status_code == 429
        assert "synthetic-private" not in response.text
    assert calls == [True]
    now[0] = 60
    assert client.get("/v1/stats", headers=bearer(credentials.agent_token)).status_code == 200
    assert len(calls) == 2


def test_stdio_scope_ignores_tenant_hints_and_permission_precedence(service):
    _, _, _, app, _, credentials, server = service
    app.state.limiter.auth_limit = 2
    for index in range(2):
        assert invoke(server, "pedigree_report", {"tenant_id": "spoof" + str(index),
                       "token": "invalid"})["error"]["code"] == "unauthorized"
    assert invoke(server, "pedigree_report")["error"]["code"] == "rate_limited"
    assert invoke(server, "pedigree_report", {"token": credentials.operator_token})["error"]["code"] == "rate_limited"
    assert set(app.state.limiter._buckets) == {("auth", "local:stdio")}


def test_parallel_real_writes_share_role_budget_without_extra_commits(service):
    db, _, graph, app, _, credentials, server = service
    app.state.limiter.write_limit = 3

    def attempt(index):
        token = credentials.agent_token if index % 2 else credentials.operator_token
        result = invoke(server, "pedigree_record_source", {"id": "parallel" + str(index), "token": token})
        return "ok" if result.get("ok") else result["error"]["code"]

    with ThreadPoolExecutor(max_workers=12) as pool:
        outcomes = list(pool.map(attempt, range(24)))
    assert outcomes.count("ok") == 3
    assert outcomes.count("rate_limited") == 21
    assert db.ro_query(graph, "MATCH(n) RETURN count(n)").result_set == [[3]]


def test_shipped_http_entrypoints_explicitly_disable_proxy_rewriting(service, monkeypatch):
    from pedigree.cli import serve

    *_, server = service
    launched = []
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: launched.append(kwargs))
    serve(Settings(_env_file=None), "127.0.0.1", 8029)
    server.run("streamable-http", "127.0.0.1", 8030)
    server.run("sse", "127.0.0.1", 8031)
    assert len(launched) == 3
    assert all(options["proxy_headers"] is False for options in launched)


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


def wire_mcp(base, headers, tool="pedigree_report", arguments=None):
    async def journey():
        async with httpx2.AsyncClient(headers=headers) as transport:
            async with Client(streamable_http_client(base + "/mcp", http_client=transport)) as client:
                result = await client.call_tool(tool, arguments or {})
                return json.loads(result.content[0].text)
    return asyncio.run(journey())


def test_tcp_mounted_mcp_crossrole_budget_and_peer_header_spoof(service):
    db, _, _, app, _, credentials, _ = service
    limiter = app.state.limiter
    limiter.write_limit = 1
    limiter.auth_limit = 2
    # The SDK session manager is single-use; give the TCP listener a fresh app,
    # retaining the same real registry, credential and explicitly shared limiter.
    tcp_app = create_app(db, Settings(_env_file=None, pedigree_admin_token="attack-local-admin"), limiter=limiter)
    with live(tcp_app) as base, httpx2.Client() as client:
        assert wire_mcp(base, bearer(credentials.operator_token), "pedigree_record_source", {"id": "wire"})["ok"]
        response = client.post(base + "/v1/sources", headers=bearer(credentials.agent_token), json={"kind": "web"})
        assert response.status_code == 429
        for index in range(2):
            result = wire_mcp(base, {"X-Forwarded-For": "192.0.2." + str(index)},
                              arguments={"token": "invalid"})
            assert result["error"]["code"] == "unauthorized"
        response = client.get(base + "/v1/stats", headers={**bearer(credentials.operator_token),
            "Forwarded": "for=198.51.100.99", "X-Forwarded-For": "192.0.2.99"})
        assert response.status_code == 429
    assert ("auth", "127.0.0.1") in limiter._buckets
    assert not any("192.0.2" in part or "198.51.100" in part for key in limiter._buckets for part in key)


def test_agent_cannot_turn_exhaustion_into_privileged_permission_or_secret_error(service):
    _, _, _, app, client, credentials, server = service
    app.state.limiter.write_limit = 1
    assert invoke(server, "pedigree_record_source", {"id": "allowed"})["ok"]
    for tool, args in (("pedigree_revoke", {"root_id": "allowed"}),
                       ("pedigree_record_source", {"kind": "human"})):
        payload = invoke(server, tool, args)
        assert payload["error"]["code"] == "forbidden"
        assert credentials.agent_token not in json.dumps(payload)
    response = client.post("/v1/revoke", headers={**bearer(credentials.agent_token),
        "X-Admin-Token": "attack-local-admin"}, json={"root_id": "allowed"})
    assert response.status_code == 403
    malformed = invoke(server, "pedigree_report", {"token": credentials.agent_token, "secret-input": "private-sentinel"})
    assert malformed["error"]["code"] == "invalid_argument"
    assert "private-sentinel" not in json.dumps(malformed)
