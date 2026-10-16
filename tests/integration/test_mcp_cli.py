"""P-016: `pedigree mcp --transport stdio` must serve a real MCP session.

Audit finding: `cli.py` called `build_mcp(settings, ...)` positionally, so the Settings
object landed in the `db` parameter and the first tool call raised AttributeError.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

from mcp import Client, StdioServerParameters

from pedigree.api.registry import TenantRegistry
from pedigree.config import graph_name
from pedigree.db.client import Db


def _drop(db: Db, gname: str, tenant: str, registry: TenantRegistry) -> None:
    try:
        db.select(gname).delete()
    except Exception:  # noqa: BLE001 - missing graph raises
        pass
    db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})


def test_mcp_cli_stdio_journey(db: Db) -> None:
    registry = TenantRegistry(db)
    tenant = "mcpcli" + uuid.uuid4().hex[:10]
    cred = registry.create_tenant(tenant)
    gname = graph_name(tenant)
    env = {**os.environ, "PEDIGREE_MCP_TENANT": tenant, "PEDIGREE_MCP_TOKEN": cred.token}
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "pedigree.cli", "mcp", "--transport", "stdio"],
        env=env,
    )

    async def journey() -> None:
        async with Client(params) as client:
            tools = await client.list_tools()
            names = [t.name for t in tools.tools]
            assert "pedigree_record_source" in names, names
            r = await client.call_tool(
                "pedigree_record_source",
                {"tenant_id": tenant, "token": cred.token, "kind": "web",
                 "uri": "https://example.test/fix-p016"},
            )
            payload = json.loads(r.content[0].text)
            assert payload["ok"] is True, payload
            node_id = payload["result"]["id"]
            r = await client.call_tool(
                "pedigree_blame",
                {"tenant_id": tenant, "token": cred.token, "node_id": node_id},
            )
            payload = json.loads(r.content[0].text)
            assert payload["ok"] is True, payload

    try:
        asyncio.run(journey())
    finally:
        _drop(db, gname, tenant, registry)
