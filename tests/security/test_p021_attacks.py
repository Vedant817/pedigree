"""Independent adversarial P-021 probes against real graph and wire transports."""
from __future__ import annotations

import asyncio
import http.client
import json
import logging
import queue
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager

import httpx2
import pytest
import uvicorn
from fastapi.testclient import TestClient
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from pedigree.api.app import CorrelationMiddleware, create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import LIMITS, Settings
from pedigree.mcp_server import build_mcp

CANARY = "attack-private-input-never-render-this"


def state(db, graph):
    return (
        db.ro_query(graph, "MATCH(n) RETURN labels(n),properties(n) ORDER BY n.id").result_set,
        db.ro_query(graph, "MATCH(a)-[r]->(b) RETURN a.id,type(r),b.id,properties(r) ORDER BY a.id,b.id,type(r)").result_set,
    )


@pytest.fixture
def attack(fresh_graph):
    db, tenant, graph = fresh_graph
    settings = Settings(pedigree_admin_token="attack-local-admin", pedigree_node_cap=2)
    registry = TenantRegistry(db, settings)
    credential = registry.create_tenant(tenant, node_cap=2)
    app = create_app(db, settings)
    # No startup reconciliation over historical tenants is needed for these probes.
    client = TestClient(app, raise_server_exceptions=False)
    sdk = build_mcp(db, settings, default_tenant_id=tenant, default_tenant_token=credential.agent_token)
    try:
        yield db, graph, client, sdk, credential, settings
    finally:
        client.close()
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})


def bearer(token):
    return {"Authorization": "Bearer " + token}


def call(sdk, name, arguments):
    result = asyncio.run(sdk.server.call_tool(name, arguments))
    return json.loads(result.content[0].text)


@pytest.mark.parametrize("bad", [
    {"type": ["source"]}, {"kind": {"source": True}},
    {"type": "source", "source_kind": ["human"]},
    {"type": "source", "integrity": {"trusted": True}},
    {"type": "source", "conf": {"x": CANARY}},
    {"type": "action", "tool": "cat", "tool_name": False},
    {"type": "action", "tool": "cat", "summary": "", "title": [CANARY]},
    {"type": "action", "tool": "cat", "relied_on": [], "memories": CANARY},
    {"type": "memory", "derived_from": [{"id": CANARY}]},
    {"type": "source", "by": "human", "uri": CANARY},
    {"type": "source", "uri": "file://a\u000bb"},
    {"type": "session_read", "session_id": [], "node_id": "absent"},
])
def test_bad_tail_unhashable_alias_and_hidden_trust_never_partially_write(attack, bad):
    db, graph, client, _, credential, settings = attack
    before = state(db, graph)
    response = client.post("/v1/events", headers={**bearer(credential.agent_token),
        "X-Admin-Token": settings.pedigree_admin_token}, json={"events": [
            {"type": "source", "id": "prefix", "uri": "valid-prefix"}, bad]})
    assert response.status_code in (422, 403), response.text
    assert response.json()["error"]["code"] in ("invalid_argument", "forbidden")
    assert CANARY not in response.text
    assert state(db, graph) == before


def test_agent_admin_header_cannot_upgrade_alias_and_quota_stays_enforced(attack):
    db, graph, client, sdk, credential, settings = attack
    headers = {**bearer(credential.agent_token), "X-Admin-Token": settings.pedigree_admin_token}
    for event in [{"kind": "human"}, {"type": "source_read", "source_kind": "human"},
                  {"kind": "source.create", "integrity": "trusted"}]:
        response = client.post("/v1/events", headers=headers, json={"events": [event]})
        assert response.status_code == 403, response.text
    assert state(db, graph)[0] == []
    response = client.post("/v1/events", headers=headers, json={"events": [
        {"kind": "web", "id": "a", "uri": "one"},
        {"kind": "web", "id": "b", "uri": "two"}]})
    assert response.status_code == 200, response.text
    before = state(db, graph)
    response = client.post("/v1/events", headers=headers, json={"events": [
        {"type": "source", "uri": "three"}]})
    assert response.status_code == 429 and response.json()["error"]["code"] == "quota_exceeded"
    payload = call(sdk, "pedigree_record_source", {"uri": "four"})
    assert payload["error"]["code"] == "quota_exceeded"
    assert state(db, graph) == before


@pytest.mark.parametrize("field", ["uri", "title", "text", "summary", "artifact"])
def test_lone_unicode_surrogate_bad_tail_rejected_before_writes(attack, field):
    db, graph, client, _, credential, _ = attack
    before = state(db, graph)
    kind = "source" if field in ("uri", "title") else ("action" if field == "summary" else "memory")
    bad = {"type": kind, field: "private-surrogate-\ud800"}
    if kind == "action":
        bad["tool"] = "cat"
    # JSON escaping sends the malformed Unicode to the server without asking the
    # HTTP client to encode the surrogate itself.
    response = client.post("/v1/events", headers={**bearer(credential.operator_token),
        "Content-Type": "application/json"}, content=json.dumps({"events": [
            {"type": "source", "id": "prefix", "uri": "valid-prefix"}, bad]}))
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_argument"
    assert state(db, graph) == before


@pytest.mark.parametrize("name,arguments", [
    ("pedigree_record_source", {"uri": "private-surrogate-\ud800"}),
    ("pedigree_remember", {"text": "private-surrogate-\udfff"}),
])
def test_mcp_lone_unicode_surrogate_is_typed_input_error(attack, name, arguments):
    db, graph, _, sdk, _, _ = attack
    before = state(db, graph)
    payload = call(sdk, name, arguments)
    assert payload["error"]["code"] == "invalid_argument", payload
    assert state(db, graph) == before


@pytest.mark.parametrize("site", ["schema", "auth", "engine"])
def test_sdk_exception_and_chained_cause_canaries_not_in_outputs_or_logs(attack, monkeypatch, caplog, site):
    db, graph, _, sdk, credential, _ = attack
    before = state(db, graph)

    def explode(*args, **kwargs):
        try:
            raise ValueError(CANARY + "-cause")
        except ValueError as cause:
            raise RuntimeError(CANARY + "-outer") from cause

    target = {"schema": "pedigree.mcp_server.ensure_schema", "engine": "pedigree.mcp_server.record_source"}
    if site == "auth":
        monkeypatch.setattr(sdk.registry, "resolve", explode)
    else:
        monkeypatch.setattr(target[site], explode)
    caplog.set_level(logging.ERROR)
    payload = call(sdk, "pedigree_record_source", {"token": credential.agent_token, "uri": "safe"})
    assert payload["error"]["code"] == "internal"
    assert len(payload["error"]["correlation_id"]) == 32
    assert CANARY not in json.dumps(payload) and CANARY not in caplog.text
    assert credential.agent_token not in json.dumps(payload) and credential.agent_token not in caplog.text
    assert caplog.records and all(record.exc_info is None for record in caplog.records)
    assert state(db, graph) == before


@pytest.mark.parametrize("finished", [False, True])
def test_after_response_start_fault_is_contained_without_second_status_or_exception_values(caplog, finished):
    sent = []

    async def endpoint(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"prefix", "more_body": not finished})
        try:
            raise ValueError(CANARY + "-cause")
        except ValueError as cause:
            raise RuntimeError(CANARY + "-outer") from cause

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    caplog.set_level(logging.ERROR)
    asyncio.run(CorrelationMiddleware(endpoint)({"type": "http", "state": {}, "headers": [
        (b"x-correlation-id", CANARY.encode())]}, receive, send))
    assert [item["status"] for item in sent if item["type"] == "http.response.start"] == [200]
    assert len([item for item in sent if item["type"] == "http.response.body"]) == (1 if finished else 2)
    assert CANARY not in str(sent) and CANARY not in caplog.text
    assert "RuntimeError" in caplog.text and "ValueError" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@contextmanager
def live(app, lifespan="off"):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, lifespan=lifespan, log_config=None, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 8
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        yield port
    finally:
        server.should_exit = True
        thread.join(timeout=8)
        sock.close()
        assert not thread.is_alive()


@pytest.mark.parametrize("path", ["/v1/events", "/mcp"])
def test_real_chunked_exact_limit_and_one_byte_overflow(attack, path):
    db, graph, client, _, credential, _ = attack
    before = state(db, graph)
    prefix = b'{"events":[]}' if path == "/v1/events" else b'{}'
    with live(client.app) as port:
        for extra in (0, 1):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            try:
                size = LIMITS["body_bytes"] + extra
                body = prefix + b" " * (size - len(prefix))
                connection.request("POST", path, body=iter([body[:31], body[31:17777], body[17777:]]),
                    headers={**bearer(credential.agent_token), "Content-Type": "application/json"}, encode_chunked=True)
                response = connection.getresponse()
                rendered = response.read().decode()
                expected = 413 if extra else (200 if path == "/v1/events" else 400)
                assert response.status == expected, rendered
                if extra:
                    assert json.loads(rendered)["error"]["code"] == "too_large"
            finally:
                connection.close()
    assert state(db, graph) == before


def test_real_http_malformed_rpc_ids_sdk_extras_and_header_default_bypasses(attack, caplog):
    db, graph, _, sdk, credential, settings = attack
    before = state(db, graph)
    caplog.set_level(logging.ERROR)
    with live(sdk.server.streamable_http_app(), lifespan="on") as port:
        url = f"http://127.0.0.1:{port}/mcp"
        for message in [
            {"jsonrpc": "2.0", "id": {CANARY: True}, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": CANARY, "method": "tools/call", "params": [CANARY]},
            {"jsonrpc": "2.0", "id": CANARY, "method": False},
        ]:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            try:
                connection.request("POST", "/mcp", json.dumps(message), {"Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream"})
                response = connection.getresponse()
                rendered = response.read().decode()
                assert response.status == 400 and CANARY not in rendered, (message, response.status, rendered)
                assert json.loads(rendered)["id"] is None
            finally:
                connection.close()

        async def probe(headers, arguments, code):
            async with httpx2.AsyncClient(headers=headers) as transport:
                async with Client(streamable_http_client(url, http_client=transport)) as mcp:
                    result = await mcp.call_tool("pedigree_record_source", arguments)
                    rendered = json.dumps(result.model_dump(), default=str)
                    payload = json.loads(result.content[0].text)
                    assert payload["error"]["code"] == code
                    assert CANARY not in rendered and credential.operator_token not in rendered

        asyncio.run(probe({}, {"uri": "default-must-not-inherit"}, "unauthorized"))
        asyncio.run(probe({"Authorization": ""}, {"token": credential.operator_token, "kind": "human"}, "unauthorized"))
        asyncio.run(probe({**bearer(credential.agent_token), "X-Admin-Token": settings.pedigree_admin_token},
            {"kind": "human"}, "forbidden"))
        asyncio.run(probe(bearer(credential.agent_token), {"kind": "web", "unknown-private-key": CANARY}, "invalid_argument"))
    assert CANARY not in caplog.text
    assert state(db, graph) == before


def test_real_stdio_bad_line_bad_id_then_valid_health_recovers():
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26",
            "capabilities": {}, "clientInfo": {"name": "p021-attack", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ]
    process = subprocess.Popen([sys.executable, "-m", "pedigree.cli", "mcp", "--transport", "stdio"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    received = queue.Queue()
    stderr = []

    def reader():
        for line in process.stdout:
            received.put(json.loads(line))

    def errors():
        stderr.extend(process.stderr)

    threading.Thread(target=reader, daemon=True).start()
    error_reader = threading.Thread(target=errors, daemon=True)
    error_reader.start()

    def send(value):
        process.stdin.write(json.dumps(value) + "\n")
        process.stdin.flush()

    try:
        send(messages[0])
        assert received.get(timeout=15)["id"] == 1
        send(messages[1])
        for raw in ['{"secret":"' + CANARY + '"\n',
                    json.dumps({"jsonrpc": "2.0", "id": [CANARY], "method": "tools/list"}) + "\n"]:
            process.stdin.write(raw)
            process.stdin.flush()
            reply = received.get(timeout=10)
            assert reply["id"] is None and reply["error"]["code"] == -32600
            assert CANARY not in json.dumps(reply)
        send({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
            "name": "pedigree_health", "arguments": {"unexpected": CANARY}}})
        reply = received.get(timeout=10)
        assert reply["id"] == 4 and "invalid_argument" in json.dumps(reply)
        assert CANARY not in json.dumps(reply)
        send({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "pedigree_health", "arguments": {}}})
        reply = received.get(timeout=10)
        assert reply["id"] == 5 and json.loads(reply["result"]["content"][0]["text"])["ok"] is True
    finally:
        process.terminate()
        process.wait(timeout=8)
        error_reader.join(timeout=5)
    assert CANARY not in "".join(stderr)
