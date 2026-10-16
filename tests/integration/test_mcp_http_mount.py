"""P-016: the REST API must serve the MCP streamable-HTTP app at /mcp (same port).

opencode.json advertises http://127.0.0.1:8000/mcp; before this fix the FastAPI app
mounted only the static UI and GET /mcp returned 404.
"""
from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx
from mcp import Client

from pedigree.api.registry import TenantRegistry
from pedigree.config import graph_name
from pedigree.db.client import Db

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_http(url: str, timeout: float = 25.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with httpx.Client(timeout=2.0) as c:
                if c.get(url).status_code == 200:
                    return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise AssertionError(f"server at {url} did not become ready")


def test_api_mounts_mcp_streamable_http(db: Db) -> None:
    registry = TenantRegistry(db)
    tenant = "mcphttp" + uuid.uuid4().hex[:10]
    cred = registry.create_tenant(tenant)
    gname = graph_name(tenant)
    port = _free_port()
    log = tempfile.NamedTemporaryFile("w+", delete=False, suffix=".log")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "pedigree.api.app:create_app",
         "--factory", "--host", "127.0.0.1", "--port", str(port)],
        stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT),
    )
    try:
        _wait_http(f"http://127.0.0.1:{port}/healthz")
        url = f"http://127.0.0.1:{port}/mcp"

        async def journey() -> None:
            async with Client(url) as client:
                tools = await client.list_tools()
                names = [t.name for t in tools.tools]
                assert "pedigree_record_source" in names, names
                r = await client.call_tool(
                    "pedigree_record_source",
                    {"tenant_id": tenant, "token": cred.token, "kind": "web",
                     "uri": "https://example.test/http-mount"},
                )
                payload = json.loads(r.content[0].text)
                assert payload["ok"] is True, payload

        try:
            asyncio.run(journey())
        except Exception as exc:
            log.flush()
            with open(log.name, encoding="utf-8", errors="replace") as fh:
                tail = fh.read()[-2000:]
            raise AssertionError(f"MCP HTTP journey failed; server log tail:\n{tail}") from exc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        log.close()
        try:
            db.select(gname).delete()
        except Exception:  # noqa: BLE001 - missing graph raises
            pass
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})
