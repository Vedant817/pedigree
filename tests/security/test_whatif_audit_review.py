"""Independent real-FalkorDB F-17/F-18 boundary review; fault injections labelled explicitly."""
from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings
from pedigree.engine.audit import audit_sources
from pedigree.engine.ingest import record_source, remember
from pedigree.engine.whatif import REGISTRY, reap_stale, whatif
from pedigree.errors import PedigreeError
from pedigree.mcp_server import build_mcp


def snapshot(db, graph):
    nodes = db.ro_query(graph, "MATCH (n) RETURN labels(n), properties(n)").result_set
    edges = db.ro_query(graph, "MATCH (a)-[r]->(b) RETURN a.id,type(r),b.id,properties(r)").result_set
    return sorted(map(repr, nodes)), sorted(map(repr, edges))


class ReviewContext(tuple):
    def __repr__(self):
        return "<isolated review fixture; credential redacted>"


@pytest.fixture
def review(fresh_graph):
    db, tenant, graph = fresh_graph
    settings = Settings(pedigree_admin_token="review-local-only")
    registry = TenantRegistry(db, settings)
    cred = registry.create_tenant(tenant)
    record_source(db, graph, tenant, id="root", kind="web", uri="local-review")
    record_source(db, graph, tenant, id="isolated", kind="web", uri="local-review")
    remember(db, graph, tenant, id="child", text="review", derived_from=["root"])
    remember(db, graph, tenant, id="grandchild", text="review", derived_from=["root", "child"])
    client = TestClient(create_app(db, settings))
    server = build_mcp(db, settings).server
    try:
        yield ReviewContext((db, tenant, graph, client, server, cred.token))
    finally:
        for name in db.list_graphs():
            if name.startswith(graph + ":wi:"):
                db.select(name).delete()
        db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": tenant})


def mcp(server, name, args):
    response = asyncio.run(server.call_tool(name, args))
    return json.loads(response.content[0].text)


@pytest.mark.parametrize("tool,args", [
    ("pedigree_whatif", {"roots": ["root"]}),
    ("pedigree_audit_sources", {"limit": 5}),
])
@pytest.mark.parametrize("attack", ["wrong_token", "mismatch"])
def test_credentials_fail_closed(review, tool, args, attack):
    db, tenant, graph, client, server, token = review
    before = snapshot(db, graph)
    supplied = dict(args, token=token)
    if attack == "wrong_token":
        supplied["token"] = "not-a-credential"
    else:
        supplied["tenant_id"] = tenant + "other"
    assert mcp(server, tool, supplied)["ok"] is False
    assert snapshot(db, graph) == before


@pytest.mark.parametrize("method,url,body", [
    ("POST", "/v1/whatif", {"roots": ["root"]}),
    ("GET", "/v1/audit/sources", None),
])
def test_rest_wrong_token(review, method, url, body):
    db, _, graph, client, _, _ = review
    before = snapshot(db, graph)
    result = client.request(method, url, json=body,
                            headers={"Authorization": "Bearer not-a-credential"})
    assert result.status_code == 401
    assert snapshot(db, graph) == before


@pytest.mark.parametrize("roots", [[], ["root"] * 9, [None], "root", [""]])
def test_whatif_malformed_roots(review, roots):
    db, _, graph, client, _, token = review
    before = snapshot(db, graph)
    result = client.post("/v1/whatif", json={"roots": roots},
                         headers={"Authorization": "Bearer " + token})
    assert result.status_code in (404, 422), result.text
    assert snapshot(db, graph) == before
    assert not [n for n in db.list_graphs() if n.startswith(graph + ":wi:")]


def test_whatif_unknown_and_cypher_root_never_modify_source(review):
    db, tenant, graph, client, server, token = review
    before = snapshot(db, graph)
    for root in ["absent", "x'}) MATCH(n) DETACH DELETE n //", "根😀"]:
        result = client.post("/v1/whatif", json={"roots": [root]},
                             headers={"Authorization": "Bearer " + token})
        assert result.status_code in (404, 422), result.text
    assert snapshot(db, graph) == before
    assert not REGISTRY.tracked(tenant)
    assert not [n for n in db.list_graphs() if n.startswith(graph + ":wi:")]


def test_whatif_copy_failure_cleans_registry_and_source(review, monkeypatch):
    db, tenant, graph, _, _, _ = review
    before = snapshot(db, graph)
    select = db.select

    class CopyFailure:
        def copy(self, destination):
            raise RuntimeError("review injected GRAPH.COPY failure")

    with monkeypatch.context() as patch:
        patch.setattr(db, "select", lambda name: CopyFailure() if name == graph else select(name))
        # statuses use Db.ro_query -> select, so expose its real read method too.
        CopyFailure.ro_query = select(graph).ro_query
        with pytest.raises(RuntimeError, match="injected"):
            whatif(db, graph, tenant, ["root"], reap=False)
    assert snapshot(db, graph) == before
    assert not REGISTRY.tracked(tenant)
    assert not [n for n in db.list_graphs() if n.startswith(graph + ":wi:")]


def test_whatif_cleanup_failure_must_not_report_deleted(review, monkeypatch):
    db, tenant, graph, _, _, _ = review
    before = snapshot(db, graph)
    select = db.select

    class DeleteFailure:
        def __init__(self, name):
            self.graph = select(name)

        def __getattr__(self, key):
            return getattr(self.graph, key)

        def delete(self):
            raise RuntimeError("review injected GRAPH.DELETE failure")

    with monkeypatch.context() as patch:
        patch.setattr(db, "select", lambda name: DeleteFailure(name)
                      if name.startswith(graph + ":wi:") else select(name))
        result = whatif(db, graph, tenant, ["root"], reap=False)
    assert snapshot(db, graph) == before
    assert result["copy"] in db.list_graphs(), "fault injection must retain real copy"
    assert result["copy_deleted"] is False
    assert result["cleanup_error"]
    assert result["copy"] in REGISTRY.pending_cleanup(tenant)
    assert reap_stale(db, tenant, graph) == [result["copy"]]
    assert result["copy"] not in db.list_graphs()
    assert not REGISTRY.pending_cleanup(tenant)


def test_whatif_fresh_untracked_copy_must_survive_reaper(review):
    db, tenant, graph, _, _, _ = review
    fresh = graph + ":wi:feedbeef"
    db.select(graph).copy(fresh)
    assert fresh in db.list_graphs()
    reaped = reap_stale(db, tenant, graph)
    assert fresh not in reaped
    assert fresh in db.list_graphs()


def test_whatif_two_active_calls_reject_third_and_clean_up(review, monkeypatch):
    db, tenant, graph, _, _, _ = review
    before = snapshot(db, graph)
    select = db.select
    entered = threading.Barrier(3)
    release = threading.Event()

    class BlockingCopy:
        def __getattr__(self, key):
            return getattr(select(graph), key)

        def copy(self, destination):
            entered.wait(timeout=10)
            assert release.wait(timeout=10)
            return select(graph).copy(destination)

    with monkeypatch.context() as patch:
        patch.setattr(db, "select", lambda name: BlockingCopy() if name == graph else select(name))
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(whatif, db, graph, tenant, ["root"], reap=False) for _ in range(2)]
            try:
                entered.wait(timeout=10)
                with pytest.raises(PedigreeError) as exc:
                    whatif(db, graph, tenant, ["root"], reap=False)
                assert exc.value.code == "rate_limited"
                assert len(REGISTRY.tracked(tenant)) == 2
            finally:
                release.set()
            results = []
            for job in jobs:
                try:
                    results.append(job.result(timeout=15))
                except Exception as exc:
                    assert isinstance(exc, PedigreeError) and exc.code == "unavailable"
                    print("Observed typed concurrent snapshot failure: " + str(exc))
    assert results and all(result["copy_deleted"] for result in results)
    assert snapshot(db, graph) == before
    assert not REGISTRY.tracked(tenant)
    assert not [n for n in db.list_graphs() if n.startswith(graph + ":wi:")]


@pytest.mark.parametrize("limit,expected", [(0,1), (-100,1), (999999,50), (1,1)])
def test_audit_limit_bounds_and_no_mutation(review, limit, expected):
    db, _, graph, client, _, token = review
    before = snapshot(db, graph)
    result = client.get(f"/v1/audit/sources?limit={limit}",
                        headers={"Authorization": "Bearer " + token})
    assert result.status_code == 200, result.text
    assert result.json()["limit"] == expected
    assert len(result.json()["sources"]) <= expected
    assert snapshot(db, graph) == before


@pytest.mark.parametrize("limit", ["abc", "1.5", "' MATCH(n) DELETE n //", "😀"])
def test_audit_malformed_limits(review, limit):
    _, _, _, client, _, token = review
    result = client.get("/v1/audit/sources", params={"limit":limit},
                        headers={"Authorization": "Bearer " + token})
    assert result.status_code == 422, result.text


def test_audit_exact_diamond_and_isolated_counts(review):
    db, _, graph, _, _, _ = review
    result = audit_sources(db, graph)
    sources = {source["id"]:source for source in result["sources"]}
    assert sources["root"]["descendants"] == 2  # shared grandchild counted once
    assert sources["isolated"]["descendants"] == 0
    assert all(source["pagerank"] >= 0 for source in sources.values())


def test_audit_empty_graph(fresh_graph):
    db, _, graph = fresh_graph
    assert audit_sources(db, graph)["sources"] == []


def test_audit_excludes_revoked_sources(review):
    db, tenant, graph, _, _, _ = review
    from pedigree.engine.revoke import revoke
    revoke(db, graph, tenant, root_id="root", reason="review")
    assert [s["id"] for s in audit_sources(db, graph)["sources"]] == ["isolated"]


def test_whatif_copy_db_error_is_mapped(review, monkeypatch):
    from redis.exceptions import ResponseError
    db, tenant, graph, _, _, _ = review
    select = db.select

    class FailingCopy:
        def __getattr__(self, key):
            return getattr(select(graph), key)

        def copy(self, destination):
            raise ResponseError("GRAPH.COPY failed, could not fork")

    with monkeypatch.context() as patch:
        patch.setattr(db, "select", lambda name: FailingCopy() if name == graph else select(name))
        with pytest.raises(PedigreeError):
            whatif(db, graph, tenant, ["root"], reap=False)


def test_two_real_tenant_tokens_cannot_audit_or_simulate_foreign_id(review):
    import uuid

    from pedigree.config import graph_name
    db, _, graph, client, _, token = review
    settings = Settings(pedigree_admin_token="review-local-only")
    registry = TenantRegistry(db, settings)
    other = "qa" + uuid.uuid4().hex[:10]
    other_graph = graph_name(other)
    cred = registry.create_tenant(other)
    try:
        record_source(db, other_graph, other, id="foreign_only", kind="web", uri="local-review")
        remember(db, other_graph, other, id="foreign_child", text="review", derived_from=["foreign_only"])
        before = snapshot(db, other_graph)
        headers = {"Authorization": "Bearer " + token}
        audit = client.get("/v1/audit/sources", headers=headers)
        assert audit.status_code == 200
        assert "foreign_only" not in [s["id"] for s in audit.json()["sources"]]
        what = client.post("/v1/whatif", headers=headers, json={"roots":["foreign_only"]})
        assert what.status_code == 404
        own_audit = client.get("/v1/audit/sources", headers={"Authorization":"Bearer " + cred.token})
        assert [s["id"] for s in own_audit.json()["sources"]] == ["foreign_only"]
        assert snapshot(db, other_graph) == before
    finally:
        db.select(other_graph).delete()
        db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id":other})


def test_audit_single_isolated_source_is_reported(fresh_graph):
    db, tenant, graph = fresh_graph
    record_source(db, graph, tenant, id="alone", kind="web", uri="local-review")
    assert db.ro_query(graph, "MATCH(n:Source) RETURN n.id,n.status").result_set == [["alone", "ok"]]
    result = audit_sources(db, graph)
    assert [source["id"] for source in result["sources"]] == ["alone"]
    assert result["sources"][0]["descendants"] == 0
    assert result["sources"][0]["pagerank"] is None


@pytest.mark.parametrize("expired", [False, True])
def test_whatif_foreign_lease_age_controls_reaping(review, expired):
    import time
    db, tenant, graph, _, _, _ = review
    copy = graph + ":wi:abcd4321"
    db.select(graph).copy(copy)
    db.query(copy, "CREATE (:WhatIfLease {owner:$owner, expires_at:$expiry})",
             {"owner":"another-worker", "expiry":int(time.time()*1000) + (-1000 if expired else 600000)})
    result = reap_stale(db, tenant, graph)
    assert (copy in result) is expired
    assert (copy in db.list_graphs()) is not expired


def test_whatif_engine_tenant_graph_mismatch_never_copies(review):
    from pedigree.errors import InvalidArgument
    db, tenant, graph, _, _, _ = review
    before = snapshot(db, graph)
    with pytest.raises(InvalidArgument):
        whatif(db, graph, tenant + "other", ["root"])
    assert snapshot(db, graph) == before
    assert not [name for name in db.list_graphs() if name.startswith(graph + ":wi:")]


def test_whatif_diff_uses_snapshot_baseline_despite_concurrent_source_insert(review, monkeypatch):
    db, tenant, graph, _, _, _ = review
    select = db.select

    class InsertBeforeCopy:
        def __getattr__(self, key):
            return getattr(select(graph), key)

        def copy(self, destination):
            record_source(db, graph, tenant, id="pre_snapshot", kind="web", uri="local-review")
            return select(graph).copy(destination)

    with monkeypatch.context() as patch:
        patch.setattr(db, "select", lambda name: InsertBeforeCopy() if name == graph else select(name))
        result = whatif(db, graph, tenant, ["root"], reap=False)
    assert result["counts"]["nodes_changed"] == 3
    assert "pre_snapshot" in result["diff"]["unchanged"]
    assert db.ro_query(graph, "MATCH(n:Node {id:'root'}) RETURN n.status").result_set == [["ok"]]
    assert db.ro_query(graph, "MATCH(n:Revocation) RETURN count(n)").result_set == [[0]]


def test_whatif_failed_cleanup_consumes_capacity_until_retry(review, monkeypatch):
    db, tenant, graph, _, _, _ = review
    select = db.select

    class DeleteFailure:
        def __init__(self, name):
            self.graph = select(name)

        def __getattr__(self, key):
            return getattr(self.graph, key)

        def delete(self):
            raise RuntimeError("review injected cleanup failure")

    with monkeypatch.context() as patch:
        patch.setattr(db, "select", lambda name: DeleteFailure(name)
                      if name.startswith(graph + ":wi:") else select(name))
        for _ in range(2):
            result = whatif(db, graph, tenant, ["root"], reap=False)
            assert result["copy_deleted"] is False
        assert len(REGISTRY.pending_cleanup(tenant)) == 2
        with pytest.raises(PedigreeError) as exc:
            whatif(db, graph, tenant, ["root"], reap=False)
        assert exc.value.code == "rate_limited"
    assert len(reap_stale(db, tenant, graph)) == 2
    assert not REGISTRY.pending_cleanup(tenant)
    assert whatif(db, graph, tenant, ["root"], reap=False)["copy_deleted"] is True


def test_whatif_lost_copy_response_deletes_materialized_copy(review, monkeypatch):
    from redis.exceptions import ConnectionError
    db, tenant, graph, _, _, _ = review
    before = snapshot(db, graph)
    select = db.select
    destinations = []

    class LostResponse:
        def __getattr__(self, key):
            return getattr(select(graph), key)

        def copy(self, destination):
            select(graph).copy(destination)
            destinations.append(destination)
            assert destination in db.list_graphs()
            raise ConnectionError("review injected lost GRAPH.COPY response")

    with monkeypatch.context() as patch:
        patch.setattr(db, "select", lambda name: LostResponse() if name == graph else select(name))
        with pytest.raises(PedigreeError) as exc:
            whatif(db, graph, tenant, ["root"], reap=False)
        assert exc.value.code == "unavailable"
    assert destinations and all(name not in db.list_graphs() for name in destinations)
    assert not REGISTRY.tracked(tenant)
    assert not REGISTRY.pending_cleanup(tenant)
    assert snapshot(db, graph) == before
