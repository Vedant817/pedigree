"""P-021 app/body boundaries; synthetic framing is separate from real HTTP tests."""
import asyncio
import logging
import uuid

import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import BodySizeMiddleware, create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import LIMITS, Settings


def run_body(chunks, headers=(), path="/v1/events"):
    messages = [{"type": "http.request", "body": part, "more_body": i < len(chunks) - 1}
                for i, part in enumerate(chunks)]
    sent, seen = [], []

    async def receive():
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    async def endpoint(scope, receive, send):
        seen.append(True)
        body = b""
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": body})

    scope = {"type": "http", "method": "POST", "path": path, "headers": list(headers),
             "query_string": b"", "http_version": "1.1", "scheme": "http", "server": ("localhost", 8000)}
    asyncio.run(BodySizeMiddleware(endpoint)(scope, receive, send))
    return sent, seen


@pytest.mark.parametrize("path", ["/v1/events", "/mcp"])
@pytest.mark.parametrize("headers", [(), ((b"content-length", b"1"),)])
def test_actual_bytes_overflow_before_downstream(path, headers):
    sent, seen = run_body([b"x" * (LIMITS["body_bytes"] - 1), b"xx"], headers, path)
    assert sent[0]["status"] == 413
    assert seen == []


def test_exact_actual_byte_limit_replayed_once():
    body = b"x" * LIMITS["body_bytes"]
    sent, seen = run_body([body[:100], body[100:]])
    assert seen == [True]
    assert sent[0]["status"] == 200
    assert sent[1]["body"] == body


@pytest.mark.parametrize("headers", [
    ((b"content-length", b"-1"),), ((b"content-length", b"invalid"),),
    ((b"content-length", b"1"), (b"content-length", b"1")),
])
def test_malformed_lengths_do_not_reach_handler(headers):
    sent, seen = run_body([b"x"], headers)
    assert sent[0]["status"] == 400
    assert seen == []


def test_disconnected_upload_does_not_reach_handler():
    sent, seen = run_body([])
    assert sent == [] and seen == []


def test_typed_error_does_not_echo_message_or_input_details():
    from pedigree.diagnostics import error_payload
    from pedigree.errors import InvalidArgument

    canary = "private-input-canary"
    payload = error_payload(InvalidArgument(canary, detail={"id": canary, "limit": 8}))
    assert canary not in str(payload)
    assert payload["code"] == "invalid_argument" and payload["detail"] == {"limit": 8}


@pytest.mark.parametrize("fault_site", ["engine", "auth"])
def test_unexpected_fault_no_input_or_exception_leak(fresh_graph, monkeypatch, caplog, fault_site):
    db, tenant, _ = fresh_graph
    settings = Settings(pedigree_admin_token="dummy-p021-admin")
    registry = TenantRegistry(db, settings)
    credential = registry.create_tenant(tenant)
    app = create_app(db, settings)
    canary = "private-exception-canary-" + uuid.uuid4().hex

    def explode(*args, **kwargs):
        raise RuntimeError(canary)

    if fault_site == "engine":
        monkeypatch.setattr("pedigree.engine.revoke.report", explode)
    else:
        monkeypatch.setattr(app.state.registry, "resolve", explode)
    caplog.set_level(logging.ERROR)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/v1/stats", headers={"Authorization": "Bearer " + credential.token,
                                                       "X-Correlation-ID": canary})
        assert response.status_code == 500
        assert canary not in response.text
        error = response.json()["error"]
        assert error["code"] == "internal" and "message" not in error
        assert uuid.UUID(error["correlation_id"])
        assert response.headers.get("x-correlation-id") == error["correlation_id"]
        assert canary not in caplog.text
        assert any("RuntimeError" in record.getMessage() for record in caplog.records)
        assert all(record.exc_info is None for record in caplog.records)
    finally:
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})
