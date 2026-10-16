"""P-016 follow-up / red-team F-1: stdio must not authorize on the tenant id alone.

Red-team finding F-1 (`docs/qa/redteam-P-016.md`): `_resolve`'s tokenless branch never
checked `default_tenant_token`, so with `PEDIGREE_MCP_TENANT` set — and even with a
WRONG `PEDIGREE_MCP_TOKEN` — tool calls without an in-band `token` were accepted; the
tenant id alone granted full tenant powers.

The tokenless convenience path stays, but it must require the configured default token
to actually resolve to the configured default tenant.
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


def _blame_tokenless(tenant: str, env_token: str | None) -> dict:
    """One real stdio journey: pedigree_blame with NO in-band token argument."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PEDIGREE_")}
    env["PEDIGREE_MCP_TENANT"] = tenant
    if env_token is not None:
        env["PEDIGREE_MCP_TOKEN"] = env_token
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "pedigree.cli", "mcp", "--transport", "stdio"],
        env=env,
    )

    async def call() -> dict:
        async with Client(params) as client:
            r = await client.call_tool(
                "pedigree_blame", {"tenant_id": tenant, "node_id": "src_does_not_exist"}
            )
            return json.loads(r.content[0].text)

    return asyncio.run(call())


def test_wrong_env_token_is_rejected(db: Db) -> None:
    """A wrong PEDIGREE_MCP_TOKEN must NOT silently authorize tokenless calls."""
    registry = TenantRegistry(db)
    tenant = "mcpsec" + uuid.uuid4().hex[:8]
    cred = registry.create_tenant(tenant)
    try:
        payload = _blame_tokenless(tenant, env_token=f"ped_{tenant}_wrongwrongwrong")
        assert payload["ok"] is False, payload
        err = payload["error"]
        assert err["code"] == "unauthorized", payload
        assert err.get("message"), payload  # actionable message, not null
    finally:
        _drop(db, graph_name(tenant), tenant, registry)


def test_missing_env_token_is_rejected(db: Db) -> None:
    """No PEDIGREE_MCP_TOKEN at all: the tenant id alone must not authorize."""
    registry = TenantRegistry(db)
    tenant = "mcpsec" + uuid.uuid4().hex[:8]
    cred = registry.create_tenant(tenant)
    try:
        assert cred.token  # created, token exists — just not configured for the server
        payload = _blame_tokenless(tenant, env_token=None)
        assert payload["ok"] is False, payload
        assert payload["error"]["code"] == "unauthorized", payload
        assert payload["error"].get("message"), payload
    finally:
        _drop(db, graph_name(tenant), tenant, registry)


def test_correct_env_token_still_works_tokenless(db: Db) -> None:
    """The documented convenience path survives: right env token + no arg = authorized."""
    registry = TenantRegistry(db)
    tenant = "mcpsec" + uuid.uuid4().hex[:8]
    cred = registry.create_tenant(tenant)
    try:
        payload = _blame_tokenless(tenant, env_token=cred.token)
        # authorized (auth passed) — the node is simply absent, which proves the engine ran
        assert payload["ok"] is False, payload
        assert payload["error"]["code"] == "not_in_graph", payload
    finally:
        _drop(db, graph_name(tenant), tenant, registry)
