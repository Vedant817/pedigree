"""Independent P-014 attacks; real DB, exact fixture-owned cleanup only."""
import asyncio
import json
import multiprocessing
import uuid

import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import get_settings, graph_name
from pedigree.db.client import Db
from pedigree.db.schema import ensure_schema, node_count
from pedigree.engine.ingest import record_source, remember
from pedigree.engine.quota import QuotaPolicy, admission, lock_key
from pedigree.errors import InvalidArgument, NotFoundInGraph, Unavailable
from pedigree.mcp_server import build_mcp


class MaskedCredential:
    def __init__(self, token, operator_token):
        self.token = token
        self.operator_token = operator_token

    def __repr__(self):
        return "<temporary masked credential>"


def snapshot(db, graph):
    return (db.ro_query(graph, "MATCH(n) RETURN labels(n),properties(n) ORDER BY n.id").result_set,
            db.ro_query(graph, "MATCH(a)-[r]->(b) RETURN a.id,type(r),b.id,properties(r) ORDER BY a.id,b.id,type(r)").result_set)


@pytest.fixture
def target(db, monkeypatch):
    monkeypatch.setenv("PEDIGREE_ADMIN_TOKEN", "independent-quota-local-admin")
    get_settings.cache_clear()
    registry = TenantRegistry(db)
    tenant = "qr" + uuid.uuid4().hex[:12]
    issued = registry.create_tenant(tenant, node_cap=2)
    credential = MaskedCredential(issued.token, issued.operator_token)
    graph = graph_name(tenant)
    ensure_schema(db, graph)
    app = create_app(db=db)
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield db, tenant, graph, credential, app, client
    finally:
        client.close()
        # Every process test joins/terminates its own workers before fixture teardown.
        db.client.connection.delete(lock_key(graph))
        db.select(graph).delete()
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})
        get_settings.cache_clear()


def post(target, path, body):
    token = target[3].operator_token if path in {"/v1/revoke", "/v1/reinstate"} else target[3].token
    return target[5].post(path, json=body, headers={"Authorization": "Bearer " + token})


def invoke(server, name, **args):
    result = asyncio.run(server.call_tool(name, args))
    return json.loads(result.content[0].text)


def test_session_ensure_read_overflow_is_unchanged(target):
    db, _, graph, *_ = target
    assert post(target, "/v1/sources", {"id": "src", "kind": "web"}).status_code == 200
    assert post(target, "/v1/memories", {"id": "mem", "text": "x"}).status_code == 200
    before = snapshot(db, graph)
    r = post(target, "/v1/sessions/read", {"session_id": "smuggled", "node_id": "src", "ensure": "yes"})
    assert r.status_code == 429, r.text
    assert snapshot(db, graph) == before


def test_batch_explicit_session_cannot_hide_growth(target):
    db, _, graph, *_ = target
    before = snapshot(db, graph)
    r = post(target, "/v1/events", {"session_id": "outer_session", "events": [
        {"type": "session"},
        {"type": "source", "uri": "redteam-uri"},
        {"type": "memory", "id": "mem", "text": "x"}]})
    assert r.status_code == 429, r.text
    assert snapshot(db, graph) == before


def test_all_public_creators_at_cap_and_edges_remain_available(target):
    db, tenant, graph, credential, *_ = target
    assert post(target, "/v1/sources", {"id": "src", "kind": "web"}).status_code == 200
    assert post(target, "/v1/memories", {"id": "mem", "text": "x"}).status_code == 200
    assert post(target, "/v1/corroborate", {"source_id": "src", "memory_id": "mem"}).status_code == 200
    before = snapshot(db, graph)
    for path, body in [("sources", {"kind": "web"}), ("memories", {"text": "x"}),
                       ("actions", {"tool": "cat"}), ("sessions", {"session_id": "new"}),
                       ("revoke", {"root_id": "src"}),
                       ("gate", {"action": {"tool": "cat"}, "record": True})]:
        r = post(target, "/v1/" + path, body)
        assert r.status_code == 429, (path, r.text)
        assert snapshot(db, graph) == before
    server = build_mcp(db=db, default_tenant_id=tenant, default_tenant_token=credential.token).server
    for name, args in [("record_source", {}), ("remember", {"text": "x"}),
                       ("record_action", {"tool": "cat"}), ("revoke", {"root_id": "src"}),
                       ("check_action", {"tool": "cat", "record": True})]:
        result = invoke(server, "pedigree_" + name, token=credential.operator_token, **args)
        assert result["error"]["code"] == "quota_exceeded", (name, result)
        assert snapshot(db, graph) == before


def test_policy_lookup_failure_cannot_fall_back_uncapped(target, monkeypatch):
    db, tenant, graph, credential, app, _ = target
    record = app.state.registry.resolve(credential.token)
    monkeypatch.setattr(app.state.registry, "resolve", lambda token: record)
    def missing(*args):
        raise NotFoundInGraph("synthetic missing policy")
    monkeypatch.setattr(app.state.registry, "get_record", missing)
    before = snapshot(db, graph)
    assert post(target, "/v1/sources", {"kind": "web"}).status_code == 404
    assert snapshot(db, graph) == before
    server = build_mcp(db=db, default_tenant_id=tenant, default_tenant_token=credential.token)
    monkeypatch.setattr(server.registry, "resolve", lambda token: record)
    monkeypatch.setattr(server.registry, "get_record", missing)
    assert invoke(server.server, "pedigree_record_source")["error"]["code"] == "not_in_graph"
    assert snapshot(db, graph) == before


def test_nested_policy_escalation_and_wrong_tenant_rejected(target):
    db, tenant, graph, *_ = target
    policy = QuotaPolicy(tenant, 1)
    before = snapshot(db, graph)
    with admission(db, graph, policy) as guarded:
        with pytest.raises(InvalidArgument):
            remember(guarded, graph, tenant, quota=QuotaPolicy(tenant, 100))
        with pytest.raises(InvalidArgument):
            remember(guarded, graph, "different", quota=policy)
    assert snapshot(db, graph) == before
    assert not db.client.connection.exists(lock_key(graph))


def test_nested_none_policy_cannot_change_tenant(target):
    db, tenant, graph, *_ = target
    before = snapshot(db, graph)
    with admission(db, graph, QuotaPolicy(tenant, 2)) as guarded:
        with pytest.raises(InvalidArgument):
            remember(guarded, graph, "different", id="foreign", quota=None)
    assert snapshot(db, graph) == before


def test_graph_binding_with_and_without_explicit_nested_policy(target):
    db, tenant, graph, *_ = target
    before = snapshot(db, graph)
    with pytest.raises(InvalidArgument):
        remember(db, graph + "wrong", tenant, quota=QuotaPolicy(tenant, 2))
    with admission(db, graph, QuotaPolicy(tenant, 2)) as guarded:
        with pytest.raises(InvalidArgument):
            remember(guarded, graph + "wrong", tenant, quota=None)
    assert snapshot(db, graph) == before


def test_canonical_sources_sessions_aliases_and_zero_growth_retries(target):
    db, _, graph, *_ = target
    body = {"session_id": "only_session", "events": [
        {"type": "session"},
        {"type": "session"},
        {"type": "source", "id": "alias_a", "uri": "canonical", "content_hash": "A" * 64},
        {"type": "source", "id": "alias_b", "uri": "canonical", "content_hash": "a" * 64},
        {"type": "read", "node_id": "alias_b"}]}
    response = post(target, "/v1/events", body)
    assert response.status_code == 200, response.text
    assert node_count(db, graph) == 2
    assert len(set(response.json()["created"])) == 1
    for _ in range(2):
        response = post(target, "/v1/events", body)
        assert response.status_code == 200, response.text
        assert node_count(db, graph) == 2
    assert post(target, "/v1/sessions", {"session_id": "only_session"}).status_code == 200
    assert post(target, "/v1/sessions/read", {"session_id": "only_session", "node_id": "alias_a", "ensure": "yes"}).status_code == 200
    before = snapshot(db, graph)
    response = post(target, "/v1/events", {"session_id": "extra_session", "events": [
        {"type": "session"},
        {"type": "source", "uri": "canonical", "content_hash": "a" * 64}]})
    assert response.status_code == 429, response.text
    assert snapshot(db, graph) == before


def test_hashless_canonical_source_retry_and_new_growth_rejection(target):
    db, _, graph, *_ = target
    body = {"session_id": "session", "events": [
        {"type": "session"},
        {"type": "source", "uri": "hashless-canonical"},
        {"type": "source", "uri": "hashless-canonical"}]}
    first = post(target, "/v1/events", body)
    assert first.status_code == 200, first.text
    assert node_count(db, graph) == 2
    second = post(target, "/v1/sources", {"kind": "web", "uri": "hashless-canonical"})
    assert second.status_code == 200, second.text
    assert set(first.json()["created"]) == {second.json()["id"]}
    before = snapshot(db, graph)
    overflow = post(target, "/v1/events", {"events": [
        {"type": "source", "uri": "hashless-canonical"},
        {"type": "source", "uri": "new-hashless"}]})
    assert overflow.status_code == 429, overflow.text
    assert snapshot(db, graph) == before


def test_zero_cap_is_rejected_before_acquiring_lock(target):
    db, tenant, graph, *_ = target
    with pytest.raises(InvalidArgument):
        QuotaPolicy(tenant, 0)
    assert not db.client.connection.exists(lock_key(graph))
    assert node_count(db, graph) == 0


def test_owner_replacement_blocks_mutation_and_cannot_unlock_replacement(target):
    db, tenant, graph, *_ = target
    with pytest.raises(Unavailable, match="ownership lost"):
        with admission(db, graph, QuotaPolicy(tenant, 2)) as guarded:
            db.client.connection.set(lock_key(graph), "redteam-replacement-owner")
            remember(guarded, graph, tenant)
    assert node_count(db, graph) == 0
    assert db.client.connection.get(lock_key(graph)) in (b"redteam-replacement-owner", "redteam-replacement-owner")


def test_completed_write_with_ambiguous_response_strands_nonexpiring_owner(target, monkeypatch):
    db, tenant, graph, *_ = target
    original = db.query
    def ambiguous(*args, **kwargs):
        original(*args, **kwargs)
        raise Unavailable("synthetic response lost after actual DB write")
    with monkeypatch.context() as scope:
        scope.setattr(db, "query", ambiguous)
        with pytest.raises(Unavailable):
            remember(db, graph, tenant, id="actual_written", quota=QuotaPolicy(tenant, 1))
    assert node_count(db, graph) == 1
    assert db.client.connection.pttl(lock_key(graph)) == -1
    with pytest.raises(Unavailable, match="writer busy"):
        remember(db, graph, tenant, quota=QuotaPolicy(tenant, 1, 0.01))
    assert node_count(db, graph) == 1


def _public_contender(settings, tenant, token, barrier, results, mode):
    db = Db(settings)
    barrier.wait(20)
    if mode == "rest":
        client = TestClient(create_app(db=db, settings=settings))
        try:
            response = client.post("/v1/memories", json={"text": "race"}, headers={"Authorization": "Bearer " + token})
            results.put("ok" if response.status_code == 200 else response.json()["error"]["code"])
        finally:
            client.close()
    else:
        server = build_mcp(db=db, settings=settings, default_tenant_id=tenant, default_tenant_token=token).server
        result = invoke(server, "pedigree_remember", text="race")
        results.put("ok" if result["ok"] else result["error"]["code"])


def test_independent_process_rest_vs_mcp_last_slot(target):
    db, tenant, graph, credential, *_ = target
    record_source(db, graph, tenant, kind="web", id="existing")
    ctx = multiprocessing.get_context("spawn")
    barrier, results = ctx.Barrier(3), ctx.Queue()
    workers = [ctx.Process(target=_public_contender, args=(get_settings(), tenant, credential.token, barrier, results, mode)) for mode in ("rest", "mcp")]
    try:
        for worker in workers:
            worker.start()
        barrier.wait(30)
        outcomes = [results.get(timeout=30) for _ in workers]
        for worker in workers:
            worker.join(15)
            assert worker.exitcode == 0
        assert sorted(outcomes) == ["ok", "quota_exceeded"], outcomes
        assert node_count(db, graph) == 2
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(15)
        assert all(not worker.is_alive() for worker in workers)
        results.close()
