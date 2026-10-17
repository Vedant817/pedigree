"""MCP P-020 admission integration with real graph writes and SDK dispatch."""
import asyncio
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
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
from pedigree.config import Settings
from pedigree.errors import RateLimited
from pedigree.mcp_server import build_mcp
from pedigree.rate_limit import RateLimiter


class ProbeLimiter:
    """An injected boundary probe, not evidence of the limiter's algorithm."""
    def __init__(self):
        self.calls = []

    def check_peer(self, peer):
        pass

    def failed_auth(self, peer):
        pass

    def admit(self, tenant, operation, **options):
        self.calls.append((tenant, operation, options))
        if len(self.calls) > 2:
            raise RateLimited("private-never-echo", detail={"retry_after": 60})


@pytest.fixture
def setup(fresh_graph):
    db, tenant, graph = fresh_graph
    registry = TenantRegistry(db)
    credentials = registry.create_tenant(tenant)
    server = build_mcp(db, default_tenant_id=tenant, default_tenant_token=credentials.agent_token)
    try:
        yield db, tenant, graph, registry, credentials, server
    finally:
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})


def invoke(server, tool, arguments=None):
    result = asyncio.run(server.server.call_tool(tool, arguments or {}))
    return json.loads(result.content[0].text)


def test_mcp_consults_injected_admission_before_third_real_write(setup):
    db, _, graph, _, _, server = setup
    limiter = ProbeLimiter()
    server.limiter = limiter
    assert invoke(server, "pedigree_record_source", {"id": "one"})["ok"]
    assert invoke(server, "pedigree_record_source", {"id": "two"})["ok"]
    payload = invoke(server, "pedigree_record_source", {"id": "three"})
    assert payload.get("error", {}).get("code") == "rate_limited", payload
    assert "private-never-echo" not in json.dumps(payload)
    assert db.ro_query(graph, "MATCH(n) RETURN count(n)").result_set == [[2]]
    assert len(limiter.calls) == 3


def test_shared_real_limiter_across_roles_servers_and_separate_reads(setup):
    db, _, graph, _, credentials, server = setup
    limiter = RateLimiter(read_limit=2, write_limit=2)
    server.limiter = limiter
    other = build_mcp(db, limiter=limiter)
    for _ in range(2):
        assert invoke(server, "pedigree_report")["ok"]
    assert invoke(other, "pedigree_report", {"token": credentials.operator_token})["error"]["code"] == "rate_limited"
    assert invoke(server, "pedigree_record_source", {"id": "agent"})["ok"]
    assert invoke(other, "pedigree_record_source", {"token": credentials.operator_token, "id": "operator"})["ok"]
    assert invoke(server, "pedigree_record_source", {"id": "blocked"})["error"]["code"] == "rate_limited"
    assert db.ro_query(graph, "MATCH(n) RETURN count(n)").result_set == [[2]]


def test_rest_and_mcp_share_the_exact_injected_instance_budget(setup):
    db, _, graph, _, credentials, server = setup
    limiter = RateLimiter(write_limit=2)
    server.limiter = limiter
    app = create_app(db, Settings(pedigree_admin_token="p020-mcp-local-admin"), limiter=limiter)
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.post("/v1/sources", headers={"Authorization": "Bearer " + credentials.agent_token},
            json={"kind": "web", "id": "rest"})
        assert response.status_code == 200, response.text
        assert invoke(server, "pedigree_record_source", {"id": "mcp"})["ok"]
        response = client.post("/v1/sources", headers={"Authorization": "Bearer " + credentials.operator_token},
            json={"kind": "web", "id": "blocked"})
        assert response.status_code == 429 and int(response.headers["Retry-After"]) > 0
        assert db.ro_query(graph, "MATCH(n) RETURN count(n)").result_set == [[2]]
    finally:
        client.close()


def test_concurrent_sdk_writes_stop_at_exact_two_admissions(setup):
    db, _, graph, _, _, server = setup
    server.limiter = RateLimiter(write_limit=2)
    with ThreadPoolExecutor(max_workers=8) as pool:
        payloads = list(pool.map(lambda index: invoke(server, "pedigree_record_source", {"id": f"node{index}"}), range(8)))
    assert sum(payload.get("ok", False) for payload in payloads) == 2
    assert sum(payload.get("error", {}).get("code") == "rate_limited" for payload in payloads) == 6
    assert db.ro_query(graph, "MATCH(n) RETURN count(n)").result_set == [[2]]


def test_validation_permission_and_unadmitted_schema_do_not_spend_budget(setup, monkeypatch):
    db, _, graph, _, credentials, server = setup
    server.limiter = RateLimiter(write_limit=1)
    schema_calls = []
    from pedigree.mcp_server import ensure_schema

    def schema(*args, **kwargs):
        schema_calls.append(True)
        return ensure_schema(*args, **kwargs)

    monkeypatch.setattr("pedigree.mcp_server.ensure_schema", schema)
    assert invoke(server, "pedigree_record_source", {"kind": "human"})["error"]["code"] == "forbidden"
    assert invoke(server, "pedigree_record_source", {"extra": "private-input"})["error"]["code"] == "invalid_argument"
    assert invoke(server, "pedigree_record_source", {"token": credentials.operator_token,
        "kind": "scanner"})["error"]["code"] == "invalid_argument"
    assert schema_calls == []
    assert invoke(server, "pedigree_record_source", {"id": "allowed"})["ok"]
    assert invoke(server, "pedigree_record_source", {"id": "blocked"})["error"]["code"] == "rate_limited"
    assert len(schema_calls) == 1
    assert db.ro_query(graph, "MATCH(n) RETURN count(n)").result_set == [[1]]


def test_admitted_engine_failure_consumes_one_write(setup):
    _, _, _, _, _, server = setup
    server.limiter = RateLimiter(write_limit=1)
    assert invoke(server, "pedigree_remember", {"derived_from": ["missing"]})["error"]["code"] == "not_in_graph"
    assert invoke(server, "pedigree_record_source", {"id": "blocked"})["error"]["code"] == "rate_limited"


def test_gate_read_recorded_gate_write_and_whatif_write_classification(setup):
    _, _, _, _, _, server = setup
    server.limiter = RateLimiter(read_limit=1, write_limit=1)
    assert invoke(server, "pedigree_check_action", {"tool": "cat"})["ok"]
    assert invoke(server, "pedigree_report")["error"]["code"] == "rate_limited"
    assert invoke(server, "pedigree_record_source", {"id": "root"})["ok"]
    assert invoke(server, "pedigree_check_action", {"tool": "cat", "record": True})["error"]["code"] == "rate_limited"
    assert invoke(server, "pedigree_whatif", {"roots": ["root"]})["error"]["code"] == "rate_limited"


@pytest.mark.parametrize("tool", ["pedigree_revoke", "pedigree_reinstate"])
def test_dry_run_destructive_bucket_and_rejected_reservation_spends_no_write(setup, tool):
    db, _, _, _, credentials, server = setup
    assert invoke(server, "pedigree_record_source", {"id": "root"})["ok"]
    limiter = RateLimiter(read_limit=2, write_limit=2, destructive_limit=1)
    operator = build_mcp(db, limiter=limiter)
    auth = {"token": credentials.operator_token, "root_id": "root"}
    assert invoke(operator, tool, {**auth, "dry_run": True})["ok"]
    assert invoke(operator, tool, auth)["error"]["code"] == "rate_limited"
    for node in ("one", "two"):
        assert invoke(operator, "pedigree_record_source", {"token": credentials.agent_token, "id": node})["ok"]
    assert invoke(operator, "pedigree_report", {"token": credentials.operator_token})["ok"]
    assert invoke(operator, "pedigree_report", {"token": credentials.operator_token})["error"]["code"] == "rate_limited"


def test_whatif_uses_write_budget_while_read_bucket_is_full(setup):
    _, _, _, _, _, server = setup
    assert invoke(server, "pedigree_record_source", {"id": "root"})["ok"]
    server.limiter = RateLimiter(read_limit=1, write_limit=1)
    assert invoke(server, "pedigree_report")["ok"]
    assert invoke(server, "pedigree_whatif", {"roots": ["root"]})["ok"]
    assert invoke(server, "pedigree_record_source", {"id": "blocked"})["error"]["code"] == "rate_limited"


def test_local_failed_auth_exact_boundary_prechecks_lookup_and_expires(setup, monkeypatch):
    _, _, _, _, _, server = setup
    now = [0.0]
    server.limiter = RateLimiter(auth_limit=2, clock=lambda: now[0])
    original = server.registry.resolve
    lookups = []

    def resolve(token):
        lookups.append(True)
        return original(token)

    monkeypatch.setattr(server.registry, "resolve", resolve)
    for token in ("invalid-one", "invalid-two"):
        assert invoke(server, "pedigree_report", {"token": token})["error"]["code"] == "unauthorized"
    for args in ({"token": "invalid-three"}, {}):
        payload = invoke(server, "pedigree_report", args)
        assert payload["error"]["code"] == "rate_limited"
        assert payload["error"]["detail"]["retry_after"] > 0
    assert len(lookups) == 2
    now[0] = 60.01
    assert invoke(server, "pedigree_report")["ok"]
    assert len(lookups) == 3


@contextmanager
def live(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    uvicorn_server = uvicorn.Server(uvicorn.Config(app, proxy_headers=False, log_level="error"))
    thread = threading.Thread(target=uvicorn_server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 8
        while not uvicorn_server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        assert uvicorn_server.started
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        uvicorn_server.should_exit = True
        thread.join(timeout=8)
        sock.close()
        assert not thread.is_alive()


def test_real_http_peer_backoff_ignores_forwarded_ip_and_counts_roles_together(setup):
    _, _, _, _, credentials, server = setup
    peers = []

    class PeerLimiter(RateLimiter):
        def check_peer(self, peer):
            peers.append(peer)
            return super().check_peer(peer)

    server.limiter = PeerLimiter(auth_limit=2, read_limit=1)
    with live(server.server.streamable_http_app()) as url:
        async def request(headers, arguments):
            async with httpx2.AsyncClient(headers=headers) as transport:
                async with Client(streamable_http_client(url, http_client=transport)) as client:
                    result = await client.call_tool("pedigree_report", arguments)
                    return json.loads(result.content[0].text)

        for index in range(2):
            result = asyncio.run(request({"X-Forwarded-For": f"203.0.113.{index + 1}"}, {"token": "invalid"}))
            assert result["error"]["code"] == "unauthorized"
        result = asyncio.run(request({"X-Forwarded-For": "203.0.113.99",
            "Forwarded": "for=198.51.100.1", "Authorization": "Bearer " + credentials.operator_token}, {}))
        assert result["error"]["code"] == "rate_limited"
        assert result["error"]["detail"]["retry_after"] > 0
    assert peers and set(peers) == {"127.0.0.1"}


@pytest.mark.parametrize("transport", ["streamable-http", "sse"])
def test_shipped_mcp_http_launch_disables_proxy_headers(setup, monkeypatch, transport):
    *_, server = setup
    launched = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: launched.append(kwargs))
    server.run(transport=transport, host="127.0.0.1", port=8019)
    assert len(launched) == 1 and launched[0]["proxy_headers"] is False
    assert launched[0]["port"] == 8019


def test_actual_stdio_failed_auth_local_scope_cannot_escape_by_tenant_hint(setup):
    _, tenant, _, _, credentials, _ = setup
    script = """
import os
from pedigree.mcp_server import build_mcp
from pedigree.rate_limit import RateLimiter
build_mcp(default_tenant_id=os.environ['P020_TENANT'],
          default_tenant_token=os.environ['P020_TOKEN'],
          limiter=RateLimiter(auth_limit=2)).run(transport='stdio')
"""
    process = subprocess.Popen([sys.executable, "-c", script], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        env={**os.environ, "P020_TENANT": tenant, "P020_TOKEN": credentials.agent_token})
    received = queue.Queue()
    errors = []

    def reader():
        for line in process.stdout:
            received.put(json.loads(line))

    def error_reader():
        errors.extend(process.stderr)

    threading.Thread(target=reader, daemon=True).start()
    stderr_thread = threading.Thread(target=error_reader, daemon=True)
    stderr_thread.start()

    def send(message):
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "p020-mcp-test", "version": "1"}}})
        assert received.get(timeout=15)["id"] == 1
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        for index, args, code in [(2, {"token": "bad-one", "tenant_id": "first"}, "unauthorized"),
                                  (3, {"token": "bad-two", "tenant_id": "second"}, "unauthorized"),
                                  (4, {"token": "bad-three", "tenant_id": "third"}, "rate_limited"),
                                  (5, {}, "rate_limited")]:
            send({"jsonrpc": "2.0", "id": index, "method": "tools/call", "params": {
                "name": "pedigree_report", "arguments": args}})
            reply = received.get(timeout=10)
            assert reply["id"] == index
            payload = json.loads(reply["result"]["content"][0]["text"])
            assert payload["error"]["code"] == code
            assert credentials.agent_token not in json.dumps(reply)
        send({"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {
            "name": "pedigree_health", "arguments": {}}})
        reply = received.get(timeout=10)
        assert json.loads(reply["result"]["content"][0]["text"])["ok"]
    finally:
        process.terminate()
        process.wait(timeout=8)
        stderr_thread.join(timeout=5)
    assert credentials.agent_token not in "".join(errors)
