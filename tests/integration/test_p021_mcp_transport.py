"""P-021 observed TCP and stdio boundaries, distinct from direct tool calls."""
from __future__ import annotations

import asyncio
import json
import os
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import pytest
from mcp import Client

from pedigree.api.registry import TenantRegistry
from pedigree.config import LIMITS

CANARY = "p021-transport-private-canary"
ROOT = Path(__file__).resolve().parents[2]
SCRIPT = '''
import os
from pedigree.mcp_server import build_mcp
s = build_mcp(default_tenant_id=os.environ['TEST_TENANT'], default_tenant_token=os.environ['TEST_TOKEN'])
original = s.registry.resolve
def resolve(token):
    if token == 'forced-registry-fault':
        raise RuntimeError('p021-transport-private-canary')
    return original(token)
s.registry.resolve = resolve
s.run(transport=os.environ['TEST_TRANSPORT'], port=int(os.environ['TEST_PORT']))
'''


@pytest.fixture
def launch(fresh_graph):
    db, tenant, graph = fresh_graph
    registry = TenantRegistry(db)
    credential = registry.create_tenant(tenant)
    processes = []
    logs = []

    def start(transport):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        log = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
        proc = subprocess.Popen([sys.executable, "-c", SCRIPT], cwd=ROOT,
            env={**os.environ, "TEST_TENANT": tenant, "TEST_TOKEN": credential.token,
                 "TEST_TRANSPORT": transport, "TEST_PORT": str(port)},
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8")
        processes.append(proc)
        logs.append(log)
        return proc, port, log

    try:
        yield start, db, graph
    finally:
        for proc in processes:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=8)
        for log in logs:
            log.seek(0)
            text = log.read()
            log.close()
            assert CANARY not in text
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})


def test_actual_tcp_safe_tools_and_malformed_envelope(launch):
    start, db, graph = launch
    proc, port, _ = start("streamable-http")
    url = f"http://127.0.0.1:{port}/mcp"
    deadline = time.monotonic() + 20
    while True:
        try:
            httpx.get(url, timeout=1)
            break
        except httpx.HTTPError:
            assert time.monotonic() < deadline and proc.poll() is None
            time.sleep(.1)

    async def journey():
        async with Client(url) as client:
            for args, code in [({"conf": CANARY}, "invalid_argument"),
                               ({"unexpected": CANARY}, "invalid_argument"),
                               ({"token": "forced-registry-fault"}, "internal")]:
                result = await client.call_tool("pedigree_record_source", args)
                payload = json.loads(result.content[0].text)
                assert payload["error"]["code"] == code
                assert CANARY not in json.dumps(payload)
                if code == "internal":
                    assert payload["error"]["correlation_id"]

    # HTTP transport must not inherit a local default credential (P-015).
    # Validation happens before authentication; the forced token triggers the fault.
    asyncio.run(journey())
    for body in [{"jsonrpc": "2.0", "id": 99, "method": CANARY, "params": CANARY},
                 {"jsonrpc": "2.0", "id": 99, "method": "tools/call", "params": {"name": CANARY, "arguments": CANARY}}]:
        response = httpx.post(url, json=body, timeout=5)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == -32600
        assert CANARY not in response.text
    response = httpx.post(url, content=(b" " * 8192 for _ in range(LIMITS["body_bytes"] // 8192 + 1)),
                          headers={"content-type": "application/json"}, timeout=5)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "too_large"
    assert db.ro_query(graph, "MATCH(n) RETURN count(n)").result_set[0][0] == 0


def test_actual_stdio_safe_tools_and_malformed_framing(launch):
    start, db, graph = launch
    proc, _, _ = start("stdio")
    received = queue.Queue()

    def reader():
        for line in proc.stdout:
            received.put(json.loads(line))

    threading.Thread(target=reader, daemon=True).start()

    def send(message):
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()

    def response(wanted):
        deadline = time.monotonic() + 15
        while True:
            item = received.get(timeout=max(.1, deadline - time.monotonic()))
            if item.get("id") == wanted:
                return item

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "p021-test", "version": "1"}}})
    assert "result" in response(1)
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    for number, args, code in [(2, {"conf": CANARY}, "invalid_argument"),
                               (3, {"unexpected": CANARY}, "invalid_argument"),
                               (4, {"token": "forced-registry-fault"}, "internal")]:
        send({"jsonrpc": "2.0", "id": number, "method": "tools/call",
              "params": {"name": "pedigree_record_source", "arguments": args}})
        result = response(number)
        payload = json.loads(result["result"]["content"][0]["text"])
        assert payload["error"]["code"] == code
        assert CANARY not in json.dumps(result)
    proc.stdin.write('{"jsonrpc":"2.0","id":[],"private":"' + CANARY + '"}\n')
    proc.stdin.flush()
    result = response(None)
    assert "error" in result
    assert CANARY not in json.dumps(result)
    proc.stdin.write('{"private":"' + CANARY + '"\n')
    proc.stdin.flush()
    assert CANARY not in json.dumps(response(None))
    send({"jsonrpc": "2.0", "id": 91, "method": "tools/call",
          "params": {"name": CANARY, "arguments": CANARY}})
    assert CANARY not in json.dumps(response(None))
    # Recover on the same stream after malformed JSON-RPC.
    send({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
          "params": {"name": "pedigree_health", "arguments": {}}})
    assert json.loads(response(5)["result"]["content"][0]["text"])["ok"] is True
    assert db.ro_query(graph, "MATCH(n) RETURN count(n)").result_set[0][0] == 0
