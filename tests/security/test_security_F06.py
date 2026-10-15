"""Security tests for F-06 MCP (red-team)."""
from __future__ import annotations

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
def db():
    return Db(get_settings())


def test_mcp_tenant_id_without_token_is_rejected(db):
    reg = TenantRegistry(db, get_settings())
    tid = "mcp" + uuid.uuid4().hex[:10]
    reg.create_tenant(tid)
    srv = build_mcp(db, get_settings())  # no default tenant/token
    async def invoke():
        return await srv.server.call_tool("pedigree_record_source", {"tenant_id": tid, "kind": "web", "uri": "x"})
    r = _run(invoke())
    payload = json.loads(r.content[0].text)
    assert payload["ok"] is False


def test_mcp_quota_enforced(db):
    reg = TenantRegistry(db, get_settings())
    tid = "mq" + uuid.uuid4().hex[:10]
    cred = reg.create_tenant(tid, node_cap=1)
    srv = build_mcp(db, get_settings(), tid, cred.token)
    # first write
    async def w1():
        return await srv.server.call_tool("pedigree_record_source", {"tenant_id": tid, "token": cred.token, "kind": "web", "uri": "x"})
    r1 = _run(w1())
    p1 = json.loads(r1.content[0].text)
    assert p1["ok"] is True
    async def w2():
        return await srv.server.call_tool("pedigree_record_source", {"tenant_id": tid, "token": cred.token, "kind": "web", "uri": "y"})
    r2 = _run(w2())
    p2 = json.loads(r2.content[0].text)
    assert p2["ok"] is False
    assert p2["error"]["code"] == "quota_exceeded"


def test_mcp_cross_tenant_token_mismatch_rejected(db):
    reg = TenantRegistry(db, get_settings())
    tid1 = "ma" + uuid.uuid4().hex[:10]
    tid2 = "mb" + uuid.uuid4().hex[:10]
    c1 = reg.create_tenant(tid1)
    reg.create_tenant(tid2)
    srv = build_mcp(db, get_settings(), tid1, c1.token)
    # use tid2 with token1
    async def invoke():
        return await srv.server.call_tool("pedigree_record_source", {"tenant_id": tid2, "token": c1.token, "kind": "web", "uri": "x"})
    r = _run(invoke())
    payload = json.loads(r.content[0].text)
    assert payload["ok"] is False
