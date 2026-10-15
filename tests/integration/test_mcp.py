import asyncio
import json
import uuid

import pytest

from pedigree.api.registry import TenantRegistry
from pedigree.config import get_settings
from pedigree.db.client import Db
from pedigree.mcp_server import build_mcp


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def tenant_and_server():
    settings = get_settings()
    db = Db(settings)
    reg = TenantRegistry(db, settings)
    tid = "mcp" + uuid.uuid4().hex[:10]
    cred = reg.create_tenant(tid)
    srv = build_mcp(db, settings, tid, cred.token)
    return tid, cred.token, srv.server


def test_health_and_record_source(tenant_and_server):
    tid, token, server = tenant_and_server
    tools = _run(server.list_tools())
    assert "pedigree_record_source" in [t.name for t in tools]

    async def invoke():
        return await server.call_tool("pedigree_record_source", {"tenant_id": tid, "token": token, "kind": "web", "uri": "u"})

    r = _run(invoke())
    payload = json.loads(r.content[0].text)
    assert payload["ok"] is True
    assert payload["result"]["status"] == "ok"


def test_not_in_graph_returns_error_payload(tenant_and_server):
    tid, token, server = tenant_and_server

    async def invoke():
        return await server.call_tool("pedigree_blame", {"tenant_id": tid, "token": token, "node_id": "ghost"})

    r = _run(invoke())
    payload = json.loads(r.content[0].text)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "not_in_graph"
