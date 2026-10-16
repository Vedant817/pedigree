"""Independent P-014 QA. Every graph/registry row here is uniquely owned."""
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
from pedigree.engine.ingest import ensure_session, record_action, record_source, remember
from pedigree.engine.quota import QuotaPolicy, admission, lock_key
from pedigree.errors import Conflict, InvalidArgument, NotFoundInGraph, QuotaExceeded, Unavailable
from pedigree.mcp_server import build_mcp


def snapshot(db, graph):
    return (
        db.ro_query(graph, "MATCH(n) RETURN labels(n),properties(n) ORDER BY n.id").result_set,
        db.ro_query(graph, "MATCH(a)-[r]->(b) RETURN a.id,type(r),b.id,properties(r) ORDER BY a.id,b.id,type(r)").result_set,
    )


class MaskedHeaders(dict):
    def __repr__(self):
        return "<temporary authorization headers>"


@pytest.fixture
def public(db, monkeypatch):
    monkeypatch.setenv("PEDIGREE_ADMIN_TOKEN", "quota-review-local-admin")
    get_settings.cache_clear()
    tenant = "qreview" + uuid.uuid4().hex[:12]
    registry = TenantRegistry(db)
    credential = registry.create_tenant(tenant, node_cap=3)
    graph = graph_name(tenant)
    ensure_schema(db, graph)
    app = create_app(db=db)
    client = TestClient(app)
    server = build_mcp(db=db, default_tenant_id=tenant, default_tenant_token=credential.token).server

    def mcp(name, **arguments):
        # Quota tests must reach admission after the role boundary.
        result = asyncio.run(server.call_tool(name, {"token": credential.operator_token, **arguments}))
        return json.loads(result.content[0].text)

    try:
        yield db, tenant, graph, client, MaskedHeaders({"Authorization": "Bearer " + credential.operator_token}), mcp, app
    finally:
        client.close()
        # All calls synchronous, and process tests join their own writers first.
        db.client.connection.delete(lock_key(graph))
        if graph in db.list_graphs():
            db.select(graph).delete()
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})
        get_settings.cache_clear()


def test_review_standalone_registry_independence_and_explicit_cap(fresh_graph):
    db, tenant, graph = fresh_graph
    with pytest.raises(NotFoundInGraph):
        TenantRegistry(db).get_record(tenant)
    remember(db, graph, tenant, id="standalone")
    before = snapshot(db, graph)
    with pytest.raises(QuotaExceeded):
        remember(db, graph, tenant, quota=QuotaPolicy(tenant, 1))
    assert snapshot(db, graph) == before


@pytest.mark.parametrize("creator", ["source", "memory", "action", "session"])
def test_review_inherited_policy_rejects_foreign_tenant_before_write(fresh_graph, creator):
    db, tenant, graph = fresh_graph
    before = snapshot(db, graph)
    with admission(db, graph, QuotaPolicy(tenant, 2)) as guarded:
        with pytest.raises(InvalidArgument, match="tenant mismatch"):
            if creator == "session":
                ensure_session(guarded, graph, "foreignreviewtenant", "foreign")
            elif creator == "source":
                record_source(guarded, graph, "foreignreviewtenant", kind="web", id="foreign")
            elif creator == "action":
                record_action(guarded, graph, "foreignreviewtenant", tool="cat", id="foreign")
            else:
                remember(guarded, graph, "foreignreviewtenant", id="foreign")
    assert snapshot(db, graph) == before


def test_review_overflow_preserves_existing_nodes_edges_and_properties(public):
    db, _, graph, client, headers, _, _ = public
    events = [{"type": "source", "id": "root", "uri": "root"},
              {"type": "memory", "id": "child", "derived_from": ["root"]}]
    assert client.post("/v1/events", headers=headers, json={"events": events}).status_code == 200
    before = snapshot(db, graph)
    rejected = [{"type": "source", "uri": "root", "id": "new_explicit"},
                {"type": "memory", "id": "overflow"}]
    response = client.post("/v1/events", headers=headers, json={"events": rejected})
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "quota_exceeded"
    assert snapshot(db, graph) == before


def test_review_source_hash_aliases_and_hashless_explicit_identity(public):
    db, _, graph, client, headers, _, _ = public
    events = [{"type": "source", "id": "hash_a", "uri": "artifact", "content_hash": "AB" * 32},
              {"type": "source", "id": "hash_b", "uri": "artifact", "content_hash": "ab" * 32},
              {"type": "source", "uri": "hashless"},
              {"type": "source", "id": "explicit", "uri": "hashless"}]
    response = client.post("/v1/events", headers=headers, json={"events": events})
    assert response.status_code == 200
    ids = response.json()["created"]
    assert ids[0] == ids[1] and ids[2] != ids[3]
    assert node_count(db, graph) == 3
    assert client.post("/v1/events", headers=headers, json={"events": events[:3]}).status_code == 200
    assert client.post("/v1/sources", headers=headers, json={"kind": "web", "uri": "hashless", "id": "other_explicit"}).status_code == 429
    assert node_count(db, graph) == 3


def test_review_session_batch_and_ensure_read_atomic_rejection(public):
    db, _, graph, client, headers, _, _ = public
    before = snapshot(db, graph)
    events = [{"type": "session", "session_id": "session_" + str(i)} for i in range(4)]
    assert client.post("/v1/events", headers=headers, json={"events": events}).status_code == 429
    assert snapshot(db, graph) == before
    assert client.post("/v1/events", headers=headers, json={"events": events[:3]}).status_code == 200
    before = snapshot(db, graph)
    response = client.post("/v1/sessions/read", headers=headers,
                           json={"session_id": "new_session", "node_id": "session_0", "ensure": "yes"})
    assert response.status_code == 429
    assert snapshot(db, graph) == before
    assert client.post("/v1/sessions", headers=headers, json={"session_id": "session_0"}).status_code == 200


def test_review_rest_mcp_gate_revoke_reinstate_and_zero_growth(public):
    db, _, graph, client, headers, mcp, _ = public
    assert mcp("pedigree_record_source", id="root", uri="root")["ok"]
    assert mcp("pedigree_revoke", root_id="root")["ok"]
    assert client.post("/v1/gate", headers=headers, json={"action": {"tool": "cat"}, "record": True}).status_code == 200
    before = snapshot(db, graph)
    assert mcp("pedigree_reinstate", root_id="root")["error"]["code"] == "quota_exceeded"
    assert client.post("/v1/reinstate", headers=headers, json={"root_id": "root"}).status_code == 429
    assert mcp("pedigree_check_action", tool="cat", record=True)["error"]["code"] == "quota_exceeded"
    assert client.post("/v1/actions", headers=headers, json={"tool": "cat"}).status_code == 429
    assert mcp("pedigree_remember", text="overflow")["error"]["code"] == "quota_exceeded"
    assert mcp("pedigree_revoke", root_id="root")["result"]["idempotent"]
    assert client.post("/v1/reinstate", headers=headers, json={"root_id": "root", "dry_run": True}).status_code == 200
    assert mcp("pedigree_check_action", tool="cat")["ok"]
    assert snapshot(db, graph) == before


def test_review_registry_lookup_failure_never_admits_uncapped(public, monkeypatch):
    db, _, graph, client, headers, _, app = public
    before = snapshot(db, graph)

    def unavailable(*args):
        raise Unavailable("quota registry unavailable")

    monkeypatch.setattr(app.state.registry, "get_record", unavailable)
    response = client.post("/v1/memories", headers=headers, json={"id": "must_not_exist"})
    assert response.status_code == 503
    assert snapshot(db, graph) == before


def _contender(settings, tenant, graph, start, queue, index):
    start.wait(15)
    try:
        remember(Db(settings), graph, tenant, id="worker_" + str(index), quota=QuotaPolicy(tenant, 1, 5))
        queue.put("created")
    except QuotaExceeded:
        queue.put("quota_exceeded")


def test_review_separate_interpreter_admission_race(fresh_graph):
    db, tenant, graph = fresh_graph
    context = multiprocessing.get_context("spawn")
    start, queue = context.Event(), context.Queue()
    workers = [context.Process(target=_contender, args=(db.settings, tenant, graph, start, queue, i)) for i in range(3)]
    try:
        for worker in workers:
            worker.start()
        start.set()
        outcomes = [queue.get(timeout=30) for _ in workers]
        for worker in workers:
            worker.join(10)
            assert worker.exitcode == 0
        assert sorted(outcomes) == ["created", "quota_exceeded", "quota_exceeded"]
        assert node_count(db, graph) == 1
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(10)
        queue.close()
        db.client.connection.delete(lock_key(graph))


def test_review_committed_write_then_timeout_retains_nonexpiring_owner(fresh_graph, monkeypatch):
    db, tenant, graph = fresh_graph
    original = db.query

    def committed_but_unknown(*args, **kwargs):
        original(*args, **kwargs)
        raise Unavailable("simulated lost reply after completed write")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(db, "query", committed_but_unknown)
            with pytest.raises(Unavailable):
                remember(db, graph, tenant, id="committed", quota=QuotaPolicy(tenant, 2))
        assert node_count(db, graph) == 1
        assert db.client.connection.pttl(lock_key(graph)) == -1
        with pytest.raises(Unavailable, match="writer busy"):
            remember(db, graph, tenant, id="blocked", quota=QuotaPolicy(tenant, 2, 0.02))
        assert node_count(db, graph) == 1
    finally:
        # The injected real write returned before the artificial timeout; no writer remains.
        db.client.connection.delete(lock_key(graph))


def test_review_known_owner_loss_blocks_write_and_preserves_replacement(fresh_graph):
    db, tenant, graph = fresh_graph
    try:
        with pytest.raises(Unavailable, match="ownership lost"):
            with admission(db, graph, QuotaPolicy(tenant, 1)) as guarded:
                db.client.connection.set(lock_key(graph), "review-replacement-owner")
                remember(guarded, graph, tenant, id="must_not_exist")
        assert node_count(db, graph) == 0
        assert db.client.connection.get(lock_key(graph)) in (b"review-replacement-owner", "review-replacement-owner")
    finally:
        db.client.connection.delete(lock_key(graph))


def test_review_constraint_rejection_releases_mutex(fresh_graph):
    db, tenant, graph = fresh_graph
    policy = QuotaPolicy(tenant, 3)
    record_source(db, graph, tenant, kind="web", id="explicit", uri="a", quota=policy)
    with pytest.raises(Conflict):
        record_source(db, graph, tenant, kind="web", id="explicit", uri="a", quota=policy)
    assert not db.client.connection.exists(lock_key(graph))
    ensure_session(db, graph, tenant, "after_conflict", quota=policy)
    assert node_count(db, graph) == 2


def test_review_all_public_creators_reject_growth_and_edges_work_at_cap(public):
    db, _, graph, client, headers, mcp, _ = public
    assert client.post("/v1/sources", headers=headers, json={"kind": "web", "id": "source", "uri": "u"}).status_code == 200
    assert client.post("/v1/memories", headers=headers, json={"id": "memory"}).status_code == 200
    assert client.post("/v1/sessions", headers=headers, json={"session_id": "session"}).status_code == 200
    before = snapshot(db, graph)
    for route, body in [
        ("sources", {"kind": "web", "uri": "new"}), ("memories", {"text": "new"}),
        ("actions", {"tool": "cat"}), ("sessions", {"session_id": "new"}),
        ("revoke", {"root_id": "source"}),
        ("gate", {"action": {"tool": "cat"}, "record": True}),
    ]:
        response = client.post("/v1/" + route, headers=headers, json=body)
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "quota_exceeded"
        assert snapshot(db, graph) == before
    for name, body in [
        ("record_source", {"uri": "new"}), ("remember", {"text": "new"}),
        ("record_action", {"tool": "cat"}), ("revoke", {"root_id": "source"}),
        ("check_action", {"tool": "cat", "record": True}),
    ]:
        assert mcp("pedigree_" + name, **body)["error"]["code"] == "quota_exceeded"
        assert snapshot(db, graph) == before
    assert client.post("/v1/corroborate", headers=headers,
                       json={"memory_id": "memory", "source_id": "source"}).status_code == 200
    assert mcp("pedigree_corroborate", memory_id="memory", source_id="source")["ok"]
    assert client.post("/v1/sessions/read", headers=headers,
                       json={"session_id": "session", "node_id": "source", "ensure": "yes"}).status_code == 200
    assert client.post("/v1/sources", headers=headers, json={"kind": "web", "uri": "u"}).status_code == 429
    assert node_count(db, graph) == 3
