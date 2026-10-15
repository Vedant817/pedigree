"""F-18 audit_sources: PageRank ranking plus the exact descendant reach count."""
from __future__ import annotations

import asyncio
import json

from pedigree.engine.audit import audit_sources
from pedigree.engine.ingest import record_source, remember


def _seed(db, gname, tenant):
    record_source(db, gname, tenant, id="s_root", kind="web", uri="http://root")
    record_source(db, gname, tenant, id="s_leaf", kind="file", uri="docs/one.md")
    for i in range(4):
        remember(db, gname, tenant, id=f"m{i}", text="t", derived_from=["s_root"])
    remember(db, gname, tenant, id="m_deep", text="t", derived_from=["m0"])
    remember(db, gname, tenant, id="m_leaf", text="t", derived_from=["s_leaf"])


def test_audit_ranks_and_counts(fresh_graph):
    db, tenant, gname = fresh_graph
    _seed(db, gname, tenant)
    result = audit_sources(db, gname, limit=10)
    sources = {s["id"]: s for s in result["sources"]}
    assert set(sources) == {"s_root", "s_leaf"}
    # algo.BFS excludes the start node, so this is the true descendant count
    assert sources["s_root"]["descendants"] == 5    # m0..m3 + m_deep
    assert sources["s_leaf"]["descendants"] == 1
    assert sources["s_root"]["pagerank"] > sources["s_leaf"]["pagerank"]
    assert result["note"]


def test_audit_limit_is_clamped(fresh_graph):
    db, tenant, gname = fresh_graph
    _seed(db, gname, tenant)
    assert audit_sources(db, gname, limit=0)["limit"] == 1
    assert audit_sources(db, gname, limit=500)["limit"] == 50


def test_audit_over_rest(fresh_graph):
    from fastapi.testclient import TestClient

    from pedigree.api.app import create_app
    from pedigree.api.registry import TenantRegistry
    from pedigree.config import Settings

    db, tenant, gname = fresh_graph
    settings = Settings(pedigree_admin_token="audit-admin")
    _seed(db, gname, tenant)
    registry = TenantRegistry(db, settings)
    cred = registry.create_tenant(tenant)
    client = TestClient(create_app(db, settings))
    r = client.get("/v1/audit/sources?limit=5",
                   headers={"Authorization": "Bearer " + cred.token})
    assert r.status_code == 200, r.text
    assert len(r.json()["sources"]) == 2
    db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": tenant})


def test_audit_over_mcp(fresh_graph):
    from pedigree.config import Settings
    from pedigree.mcp_server import build_mcp

    db, tenant, gname = fresh_graph
    settings = Settings(pedigree_admin_token="audit-admin")
    _seed(db, gname, tenant)
    from pedigree.api.registry import TenantRegistry

    registry = TenantRegistry(db, settings)
    cred = registry.create_tenant(tenant)
    server = build_mcp(db, settings).server

    async def run():
        tools = {t.name: t for t in await server.list_tools()}
        assert "pedigree_audit_sources" in tools
        return await server.call_tool("pedigree_audit_sources",
                                      {"token": cred.token, "limit": 3})
    payload = json.loads(asyncio.run(run()).content[0].text)
    assert payload["ok"] is True
    assert len(payload["result"]["sources"]) == 2
    db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": tenant})
