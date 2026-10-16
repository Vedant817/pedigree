"""Independent P-021 QA: owned real graph, synthetic ASGI and real TCP evidence."""
import asyncio
import hashlib
import http.client
import json
import logging
import socket
import subprocess
import sys
import threading
import time
import uuid

import pytest
import uvicorn
from fastapi.testclient import TestClient
from mcp import Client

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import LIMITS, Settings, graph_name
from pedigree.db.schema import ensure_schema
from pedigree.http_boundary import BodySizeMiddleware
from pedigree.mcp_server import build_mcp


def snapshot(db, graph):
    return (
        db.ro_query(graph, "MATCH(n) RETURN labels(n),properties(n) ORDER BY n.id").result_set,
        db.ro_query(graph, "MATCH(a)-[r]->(b) RETURN a.id,type(r),b.id,properties(r) ORDER BY a.id,b.id,type(r)").result_set,
    )


@pytest.fixture
def review(db):
    settings = Settings(pedigree_admin_token="p021-review-local-admin")
    tenant = "vreview" + uuid.uuid4().hex[:12]
    registry = TenantRegistry(db, settings)
    credential = registry.create_tenant(tenant)
    graph = graph_name(tenant)
    ensure_schema(db, graph)
    app = create_app(db, settings)
    server = build_mcp(db=db, settings=settings).server
    with TestClient(app, raise_server_exceptions=False) as client:
        try:
            yield db, graph, client, {"Authorization": "Bearer " + credential.operator_token}, server, credential.operator_token
        finally:
            if graph in db.list_graphs():
                db.select(graph).delete()
            db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})


BAD_EVENTS = [
    {"type": "source", "conf": 5},
    {"type": "source", "conf": [False]},
    {"type": "source", "uri": "bad\x00uri"},
    {"type": "source", "uri": "bad\nuri"},
    {"type": "source", "title": "bad\x7ftitle"},
    {"type": "source", "content_hash": "z" * 64},
    {"type": "source", "uri": "x" * (LIMITS["uri_len"] + 1)},
    {"type": "source", "id": True},
    {"type": "memory", "derived_from": "abc"},
    {"type": "memory", "derived_from": [None]},
    {"type": "memory", "text": "bad\rprose"},
    {"type": "memory", "artifact": "bad\tartifact"},
    {"type": "memory", "text": None},
    {"type": "action", "tool": "cat", "artifacts": 5},
    {"type": "action", "tool": "cat", "artifacts": [True]},
    {"type": "action", "tool": "cat", "tool_name": "different"},
    {"type": "action", "tool": "cat", "summary": "a", "title": "b"},
    {"type": "action", "tool": "cat", "relied_on": [], "memories": ["x"]},
    {"type": "source", "kind": "web", "source_kind": "file"},
    {"type": "session"},
    {"type": "session_read", "session_id": "s"},
    {"type": "unknown"},
    {"type": "source", "secret-extra-canary": "private-canary"},
    False,
    None,
    [],
]


@pytest.mark.parametrize("bad", BAD_EVENTS)
def test_review_bad_tail_is_rejected_before_any_write(review, bad):
    db, graph, client, headers, _, _ = review
    before = snapshot(db, graph)
    response = client.post("/v1/events", headers=headers, json={"events": [
        {"type": "source", "id": "must_not_exist", "uri": "valid-prefix"}, bad]})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_argument"
    assert "private-canary" not in response.text and "secret-extra-canary" not in response.text
    assert snapshot(db, graph) == before


@pytest.mark.parametrize("endpoint,payload", [
    ("/v1/sources", {"kind": "web", "conf": "secret-input"}),
    ("/v1/memories", {"text": True}),
    ("/v1/actions", {"tool": "cat", "relied_on": "abc"}),
    ("/v1/revoke", {"root_id": "root", "dry_run": "false"}),
    ("/v1/gate", {"action": {"tool": "cat"}, "max_depth": True}),
])
def test_review_strict_rest_scalar_types(review, endpoint, payload):
    db, graph, client, headers, _, _ = review
    before = snapshot(db, graph)
    response = client.post(endpoint, headers=headers, json=payload)
    assert response.status_code == 422, response.text
    assert "secret-input" not in response.text
    assert snapshot(db, graph) == before


def test_review_aliases_prose_and_unknown_runtime_survive(review):
    db, graph, client, headers, _, _ = review
    response = client.post("/v1/events", headers=headers, json={"runtime": "future-runtime", "events": [
        {"type": "source.create", "id": "capture", "source_kind": "file", "uri": "A File.txt", "content_hash": "A" * 64},
        {"type": "remember", "id": "memo", "text": "line one\n\tline two", "derived_from": ["capture"]},
        {"type": "tool_use", "tool_name": "cat", "title": "read\n\tfile", "memories": ["memo"]},
    ]})
    assert response.status_code == 200, response.text
    ids = response.json()["created"]
    assert len(ids) == 3
    expected_hash = hashlib.sha256(b"line one\n\tline two").hexdigest()
    assert db.ro_query(graph, "MATCH(m:Memory {id:'memo'}) RETURN m.content_hash").result_set == [[expected_hash]]
    assert db.ro_query(graph, "MATCH(m:Memory {id:'memo'})-[:DERIVED_FROM]->(s:Source) RETURN s.id").result_set == [[ids[0]]]


@pytest.mark.parametrize("name,arguments", [
    ("pedigree_remember", {"derived_from": "abc"}),
    ("pedigree_remember", {"text": True}),
    ("pedigree_record_source", {"uri": "bad\nuri"}),
    ("pedigree_record_source", {"conf": [None]}),
    ("pedigree_record_action", {"tool": "cat", "artifacts": 5}),
    ("pedigree_revoke", {"root_id": "x", "dry_run": "false"}),
    ("pedigree_check_action", {"tool": "cat", "max_depth": True}),
    ("pedigree_health", {"secret-extra-canary": "private-canary"}),
])
def test_review_direct_sdk_strict_validation_without_reflection(review, name, arguments):
    db, graph, _, _, server, token = review
    before = snapshot(db, graph)
    if name != "pedigree_health":
        arguments = {"token": token, **arguments}
    result = asyncio.run(server.call_tool(name, arguments))
    rendered = json.dumps(result.model_dump(), default=str)
    assert token not in rendered and "private-canary" not in rendered and "secret-extra-canary" not in rendered
    assert "invalid_argument" in rendered
    assert snapshot(db, graph) == before


@pytest.mark.parametrize("path", ["/v1/events", "/mcp"])
@pytest.mark.parametrize("size", [LIMITS["body_bytes"], LIMITS["body_bytes"] + 1])
def test_review_actual_tcp_chunked_limit(path, size):
    seen = []

    async def endpoint(scope, receive, send):
        if scope["type"] != "http":
            return
        request = await receive()
        seen.append(len(request["body"]))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(BodySizeMiddleware(endpoint), lifespan="off", log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            body = [b"x" * 17000 for _ in range(size // 17000)]
            body.append(b"x" * (size % 17000))
            connection.request("POST", path, body=iter(body), encode_chunked=True)
            response = connection.getresponse()
            assert response.status == (200 if size == LIMITS["body_bytes"] else 413)
            response.read()
        finally:
            connection.close()
        assert seen == ([size] if size == LIMITS["body_bytes"] else [])
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()


def test_review_disconnect_never_dispatches_partial_body():
    seen, sent = [], []
    messages = [{"type": "http.request", "body": b"partial", "more_body": True}, {"type": "http.disconnect"}]

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    async def endpoint(scope, receive, send):
        seen.append(True)

    asyncio.run(BodySizeMiddleware(endpoint)({"type": "http", "headers": []}, receive, send))
    assert seen == [] and sent == []


@pytest.mark.parametrize("site", ["engine", "auth"])
def test_review_actual_uvicorn_fault_response_and_logs_are_secret_free(review, monkeypatch, caplog, site):
    _, _, client, headers, _, _ = review
    canary = "ped_private_fault_" + uuid.uuid4().hex

    def explode(*args, **kwargs):
        raise RuntimeError(canary)

    if site == "engine":
        monkeypatch.setattr("pedigree.engine.revoke.report", explode)
    else:
        monkeypatch.setattr(client.app.state.registry, "resolve", explode)
    caplog.set_level(logging.ERROR)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    # TestClient already ran lifespan. This is actual TCP/uvicorn dispatch using
    # that app; no second startup-resume against unrelated historical tenants.
    server = uvicorn.Server(uvicorn.Config(client.app, lifespan="off", log_config=None, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request("GET", "/v1/stats", headers={**headers, "X-Correlation-ID": canary})
            response = connection.getresponse()
            body = response.read().decode()
            assert response.status == 500
            payload = json.loads(body)["error"]
            assert payload["code"] == "internal" and "message" not in payload
            assert uuid.UUID(payload["correlation_id"]).hex == payload["correlation_id"]
            assert response.getheader("x-correlation-id") == payload["correlation_id"]
            assert canary not in body
        finally:
            connection.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()
    assert canary not in caplog.text
    assert any("RuntimeError" in record.getMessage() for record in caplog.records)
    assert all(record.exc_info is None for record in caplog.records)


def test_review_actual_stdio_sdk_does_not_reflect_malformed_arguments():
    canary = "private-stdio-" + uuid.uuid4().hex
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "p021-qa", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "pedigree_health", "arguments": {"unexpected": canary}}},
    ]
    process = subprocess.run([sys.executable, "-m", "pedigree.cli", "mcp", "--transport", "stdio"],
                             input="".join(json.dumps(item) + "\n" for item in messages),
                             capture_output=True, text=True, timeout=20)
    assert process.returncode == 0
    assert canary not in process.stdout and canary not in process.stderr
    responses = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
    reply = next(item for item in responses if item.get("id") == 2)
    rendered = json.dumps(reply)
    assert "invalid_argument" in rendered and "unexpected" not in rendered


def test_review_actual_http_sdk_and_envelope_do_not_reflect_input(review, caplog):
    _, _, _, _, sdk, _ = review
    canary = "private-http-" + uuid.uuid4().hex
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(sdk.streamable_http_app(), log_config=None, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started

        async def journey():
            async with Client(f"http://127.0.0.1:{port}/mcp", read_timeout_seconds=5) as client:
                result = await client.call_tool("pedigree_health", {"unexpected": canary})
                rendered = json.dumps(result.model_dump(), default=str)
                assert "invalid_argument" in rendered and canary not in rendered

        asyncio.run(journey())
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request("POST", "/mcp", body=json.dumps({"jsonrpc": "2.0", "id": canary, "method": False}),
                               headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            assert response.status == 400
            body = response.read().decode()
            assert canary not in body and "Invalid JSON-RPC message" in body
        finally:
            connection.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()
    assert canary not in caplog.text


def test_review_schema_fault_before_mcp_tool_body_is_contained(review, monkeypatch, caplog):
    db, graph, _, _, server, token = review
    before = snapshot(db, graph)
    canary = "ped_schema_fault_" + uuid.uuid4().hex

    def explode(*args, **kwargs):
        raise RuntimeError(canary)

    monkeypatch.setattr("pedigree.mcp_server.ensure_schema", explode)
    caplog.set_level(logging.ERROR)
    result = asyncio.run(server.call_tool("pedigree_report", {"token": token}))
    payload = json.loads(result.content[0].text)
    assert payload["error"]["code"] == "internal"
    assert uuid.UUID(payload["error"]["correlation_id"])
    assert canary not in json.dumps(payload) and canary not in caplog.text
    assert any("UnexpectedToolError" in record.getMessage() for record in caplog.records)
    assert all(record.exc_info is None for record in caplog.records)
    assert snapshot(db, graph) == before
