"""Role/header checks through the installed SDK and a real TCP ASGI server."""
import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from pedigree.api.registry import TenantRegistry
from pedigree.engine.ingest import record_source


@pytest.fixture
def live_mcp(fresh_graph):
    db, tenant, graph = fresh_graph
    registry = TenantRegistry(db)
    credential = registry.create_tenant(tenant)
    record_source(db, graph, tenant, id="root", kind="web")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "pedigree.api.app:create_app", "--factory",
                                "--host", "127.0.0.1", "--port", str(port)],
                               cwd=Path(__file__).resolve().parents[2],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.1)
        else:
            pytest.fail("owned MCP subprocess did not become ready")
        yield db, tenant, graph, credential, f"http://127.0.0.1:{port}/mcp"
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})


async def invoke(url, header, tool="pedigree_revoke", arguments=None):
    headers = {} if header is None else {"Authorization": header}
    async with httpx2.AsyncClient(headers=headers) as transport_client:
        transport = streamable_http_client(url, http_client=transport_client)
        async with Client(transport) as client:
            response = await client.call_tool(tool, arguments or {"root_id": "root"})
            return json.loads(response.content[0].text)


def test_http_header_only_operator_and_agent_roles(live_mcp):
    _, _, _, cred, url = live_mcp
    async def run():
        denied = await invoke(url, "Bearer " + cred.agent_token)
        assert denied["error"]["code"] == "forbidden"
        allowed = await invoke(url, "Bearer " + cred.operator_token)
        assert allowed["ok"] is True
        reinstated = await invoke(url, "Bearer " + cred.operator_token, "pedigree_reinstate")
        assert reinstated["ok"] is True
    asyncio.run(run())


@pytest.mark.parametrize("header_kind", ["invalid", "empty", "double-space", "wrong-scheme", "conflicting-agent"])
def test_http_supplied_header_never_falls_back_to_operator_tool_token(live_mcp, header_kind):
    _, _, _, cred, url = live_mcp
    header = {"invalid": "Bearer no-such-credential", "empty": "",
              "double-space": "Bearer  " + cred.operator_token, "wrong-scheme": "Basic ignored",
              "conflicting-agent": "Bearer " + cred.agent_token}[header_kind]
    result = asyncio.run(invoke(url, header, arguments={"token": cred.operator_token, "root_id": "root"}))
    assert result["error"]["code"] == "unauthorized"


def test_http_concurrent_principals_do_not_leak_roles(live_mcp):
    _, _, _, cred, url = live_mcp
    async def run():
        # Dry-run prevents the authorized requests from racing graph state.
        results = await asyncio.gather(*[
            invoke(url, "Bearer " + (cred.operator_token if index % 2 else cred.agent_token),
                   arguments={"root_id": "root", "dry_run": True})
            for index in range(8)])
        for index, result in enumerate(results):
            if index % 2:
                assert result["ok"] is True
            else:
                assert result["error"]["code"] == "forbidden"
    asyncio.run(run())


def test_http_role_is_checked_per_message_not_session(live_mcp):
    _, _, _, cred, url = live_mcp
    async def run():
        async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + cred.operator_token}) as transport_client:
            async with Client(streamable_http_client(url, http_client=transport_client)) as client:
                first = await client.call_tool("pedigree_revoke", {"root_id": "root", "dry_run": True})
                assert json.loads(first.content[0].text)["ok"] is True
                transport_client.headers["Authorization"] = "Bearer " + cred.agent_token
                second = await client.call_tool("pedigree_revoke", {"root_id": "root", "dry_run": True})
                assert json.loads(second.content[0].text)["error"]["code"] == "forbidden"
                transport_client.headers["Authorization"] = "Bearer invalid"
                third = await client.call_tool("pedigree_revoke", {"root_id": "root", "token": cred.operator_token})
                assert json.loads(third.content[0].text)["error"]["code"] == "unauthorized"
    asyncio.run(run())
