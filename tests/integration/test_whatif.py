"""F-17 what-if: revoke on a copy, diff, delete - the real graph is never written."""
from __future__ import annotations

import pytest

from pedigree.config import graph_name
from pedigree.db.schema import check_invariants
from pedigree.engine.ingest import get_node_statuses
from pedigree.engine.revoke import revoke
from pedigree.engine.whatif import whatif
from pedigree.errors import InvalidArgument


def _build(db, gname, tenant):
    from pedigree.engine.ingest import record_action, record_source, remember

    record_source(db, gname, tenant, id="s_bad", kind="web", uri="http://bad/x")
    record_source(db, gname, tenant, id="s_doc", kind="file", uri="docs/README.md")
    remember(db, gname, tenant, id="m1", text="from bad", derived_from=["s_bad"])
    remember(db, gname, tenant, id="m2", text="supported", derived_from=["s_bad"],
             corroborated_by=["s_doc"])
    remember(db, gname, tenant, id="m4", text="dependent of preserved", derived_from=["m2"])
    record_action(db, gname, tenant, id="a_push", tool="git push", summary="push",
                  relied_on=["m1", "m4"], effect="irreversible", risk="high")


def test_whatif_reports_the_diff_without_writing_the_real_graph(fresh_graph):
    db, tenant, gname = fresh_graph
    _build(db, gname, tenant)
    before = get_node_statuses(db, gname, ["s_bad", "m1", "m2", "m4", "a_push"])
    result = whatif(db, gname, tenant, ["s_bad"])
    assert result["counts"]["would_taint"] == 2          # m1 + a_push
    assert sorted(result["diff"]["would_preserve"]) == ["m2"]
    assert "m4" in result["diff"]["unchanged"]            # dependent of a preserved node
    assert result["irreversible"] and result["irreversible"][0]["id"] == "a_push"
    assert result["copy_deleted"] is True
    # the real graph is untouched and the copy is gone
    assert get_node_statuses(db, gname, ["s_bad", "m1", "m2", "m4", "a_push"]) == before
    assert not [g for g in db.list_graphs() if g.startswith(f"{gname}:wi:")]
    assert check_invariants(db, gname, expected_tenant=tenant) == []


def test_whatif_matches_a_real_revoke_on_the_same_graph(fresh_graph):
    """The copy's outcome must equal what a real revoke would produce (the point of using the
    real engine on the copy)."""
    db, tenant, gname = fresh_graph
    _build(db, gname, tenant)
    result = whatif(db, gname, tenant, ["s_bad"])
    real = revoke(db, gname, tenant, root_id="s_bad", reason="real")
    for node in ("m1", "m2", "m4", "a_push"):
        expected = ("tainted" if node in result["diff"]["would_taint"]
                    else "preserved" if node in result["diff"]["would_preserve"] else "ok")
        assert get_node_statuses(db, gname, [node])[node] == expected, node
    assert real["counts"]["tainted"] == result["counts"]["would_taint"]

    # a second what-if on the already-revoked root reports nothing to change
    again = whatif(db, gname, tenant, ["s_bad"])
    assert again["counts"]["nodes_changed"] == 0


def test_whatif_reaps_stale_copies(fresh_graph):
    db, tenant, gname = fresh_graph
    _build(db, gname, tenant)
    from pedigree.config import whatif_graph_name

    stale = whatif_graph_name(tenant, "deadbeef")
    db.select(gname).copy(stale)
    assert stale in db.list_graphs()
    whatif(db, gname, tenant, ["s_bad"])
    assert stale not in db.list_graphs()
    assert not [g for g in db.list_graphs() if g.startswith(f"{gname}:wi:")]


def test_whatif_rejects_empty_and_oversized_root_lists(fresh_graph):
    db, tenant, gname = fresh_graph
    with pytest.raises(InvalidArgument):
        whatif(db, gname, tenant, [])
    with pytest.raises(InvalidArgument):
        whatif(db, gname, tenant, [f"r{i}" for i in range(9)])


def test_whatif_is_available_over_rest_and_mcp():
    import asyncio
    import json

    from fastapi.testclient import TestClient

    from pedigree.api.app import create_app
    from pedigree.api.registry import TenantRegistry
    from pedigree.config import Settings
    from pedigree.mcp_server import build_mcp

    settings = Settings(pedigree_admin_token="wi-admin")
    db = None
    from pedigree.db.client import Db

    db = Db(settings)
    registry = TenantRegistry(db, settings)
    client = TestClient(create_app(db, settings))
    tenant = "wi" + "".join(__import__("secrets").choice("0123456789abcdef") for _ in range(11))
    cred = registry.create_tenant(tenant)
    gname = graph_name(tenant)
    try:
        _build(db, gname, tenant)
        headers = {"Authorization": "Bearer " + cred.token}
        r = client.post("/v1/whatif", headers=headers, json={"roots": ["s_bad"]})
        assert r.status_code == 200, r.text
        assert r.json()["counts"]["would_taint"] == 2
        server = build_mcp(db, settings).server

        async def run():
            tools = {t.name: t for t in await server.list_tools()}
            assert "pedigree_whatif" in tools
            return await server.call_tool("pedigree_whatif", {"token": cred.token,
                                                              "roots": ["s_bad"]})
        response = asyncio.run(run())
        payload = json.loads(response.content[0].text)
        assert payload["ok"] is True
        assert payload["result"]["counts"]["would_taint"] == 2
    finally:
        try:
            db.select(gname).delete()
        except Exception:  # noqa: BLE001
            pass
        db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": tenant})
