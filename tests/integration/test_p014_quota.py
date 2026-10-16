# All fixtures below own exactly one temporary graph and registry row.
import asyncio
import json
import multiprocessing
import os
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import get_settings, graph_name
from pedigree.db.client import Db
from pedigree.db.schema import ensure_schema, node_count
from pedigree.engine.ingest import corroborate, ensure_session, record_source, remember, session_read
from pedigree.engine.quota import QuotaPolicy, admission, lock_key, preflight
from pedigree.engine.revoke import revoke
from pedigree.errors import QuotaExceeded, Unavailable
from pedigree.mcp_server import build_mcp


def test_source_and_session_retry_at_cap(fresh_graph):
    db, tenant, graph = fresh_graph
    policy = QuotaPolicy(tenant, 2)
    first = record_source(db, graph, tenant, kind="web", uri="https://quota.example/a", quota=policy)
    ensure_session(db, graph, tenant, "session_q", quota=policy)
    assert (
        record_source(db, graph, tenant, kind="web", uri="https://quota.example/a", quota=policy).id
        == first.id
    )
    ensure_session(db, graph, tenant, "session_q", quota=policy)
    with pytest.raises(QuotaExceeded):
        ensure_session(db, graph, tenant, "session_other", quota=policy)
    assert node_count(db, graph) == 2


def test_preflight_rejects_without_writes(fresh_graph):
    db, tenant, graph = fresh_graph
    with pytest.raises(QuotaExceeded):
        with admission(db, graph, QuotaPolicy(tenant, 1)) as locked:
            preflight(
                locked,
                graph,
                tenant,
                [{"op": "source", "kind": "web", "uri": "u"}, {"op": "session", "session_id": "sess"}],
            )
    assert node_count(db, graph) == 0


class _MaskedHeaders(dict):
    def __repr__(self):
        return "<tenant authorization headers>"


class _MaskedCredential:
    def __init__(self, credential):
        self.token = credential.token

    def __repr__(self):
        return "<temporary tenant credential>"


@pytest.fixture
def quota_public(db, monkeypatch):
    monkeypatch.setenv("PEDIGREE_ADMIN_TOKEN", "quota-local-test-admin")
    get_settings.cache_clear()
    tenant = "quota" + uuid.uuid4().hex[:12]
    registry = TenantRegistry(db)
    credential = registry.create_tenant(tenant, node_cap=5)
    graph = graph_name(tenant)
    ensure_schema(db, graph)
    app = create_app()
    client = TestClient(app)
    headers = _MaskedHeaders({"Authorization": "Bearer " + credential.token})
    try:
        yield db, tenant, graph, client, headers, _MaskedCredential(credential)
    finally:
        client.close()
        # Processes are joined before this fixture releases owned data.
        db.client.connection.delete(lock_key(graph))
        if graph in db.list_graphs():
            db.select(graph).delete()
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})
        get_settings.cache_clear()


def snapshot(db, graph):
    return (
        db.ro_query(graph, "MATCH(n) RETURN labels(n),properties(n) ORDER BY n.id").result_set,
        db.ro_query(
            graph, "MATCH(a)-[r]->(b) RETURN a.id,type(r),b.id,properties(r) ORDER BY a.id,b.id,type(r)"
        ).result_set,
    )


def test_rest_batch_overflow_snapshot_and_exact_fit(quota_public):
    db, tenant, graph, client, headers, _ = quota_public
    events = [{"type": "memory", "id": f"mem_{i}", "text": "x"} for i in range(6)]
    before = snapshot(db, graph)
    response = client.post("/v1/events", headers=headers, json={"events": events})
    assert response.status_code == 429, response.text
    assert response.json()["error"]["code"] == "quota_exceeded"
    assert snapshot(db, graph) == before
    assert client.post("/v1/events", headers=headers, json={"events": events[:5]}).status_code == 200
    before = snapshot(db, graph)
    assert client.post("/v1/events", headers=headers, json={"events": events[5:]}).status_code == 429
    assert snapshot(db, graph) == before


def test_mixed_batch_hash_identity_aliases_and_sessions(quota_public):
    db, tenant, graph, client, headers, _ = quota_public
    digest = "a" * 64
    events = [
        {"type": "session", "session_id": "sess"},
        {"type": "session", "session_id": "sess"},
        {"type": "source", "id": "capture_a", "uri": "u", "content_hash": digest.upper()},
        {"type": "source", "id": "capture_b", "uri": "u", "content_hash": digest},
        {"type": "source", "uri": "hashless"},
        {"type": "source", "uri": "hashless"},
        {"type": "memory", "id": "memory_alias", "derived_from": ["capture_b"], "session_id": "sess"},
        {"type": "action", "id": "act_alias", "tool": "cat", "relied_on": ["capture_a"]},
    ]
    r = client.post("/v1/events", headers=headers, json={"events": events})
    assert r.status_code == 200, r.text
    ids = r.json()["created"]
    assert ids[0] == ids[1] and ids[2] == ids[3]
    assert node_count(db, graph) == 5
    retry = client.post("/v1/events", headers=headers, json={"events": events[:6]})
    assert retry.status_code == 200, retry.text
    assert node_count(db, graph) == 5
    edges = snapshot(db, graph)[1]
    assert any(row[:3] == ["memory_alias", "DERIVED_FROM", "capture_a"] for row in edges)


def test_session_only_batch_and_read_at_cap(quota_public):
    db, tenant, graph, client, headers, _ = quota_public
    events = [{"type": "session", "session_id": f"sess_{i}"} for i in range(6)]
    assert client.post("/v1/events", headers=headers, json={"events": events}).status_code == 429
    assert node_count(db, graph) == 0
    assert client.post("/v1/events", headers=headers, json={"events": events[:5]}).status_code == 200
    assert client.post("/v1/sessions", headers=headers, json={"session_id": "sess_0"}).status_code == 200
    assert client.post("/v1/sessions", headers=headers, json={"session_id": "sess_new"}).status_code == 429
    r = client.post(
        "/v1/sessions/read",
        headers=headers,
        json={"session_id": "sess_0", "node_id": "sess_1", "ensure": "yes"},
    )
    assert r.status_code == 200, r.text
    assert node_count(db, graph) == 5


def test_gate_record_and_mcp_parity(quota_public):
    db, tenant, graph, client, headers, credential = quota_public
    srv = build_mcp(db=db, default_tenant_id=tenant, default_tenant_token=credential.token).server

    def invoke(name, **args):
        result = asyncio.run(srv.call_tool(name, args))
        return json.loads(result.content[0].text)

    first = invoke("pedigree_record_source", uri="u")
    assert first["ok"], first
    for _ in range(4):
        assert (
            client.post(
                "/v1/gate", headers=headers, json={"action": {"tool": "cat"}, "record": True}
            ).status_code
            == 200
        )
    assert invoke("pedigree_record_source", uri="u")["ok"]
    assert invoke("pedigree_record_source", uri="v")["error"]["code"] == "quota_exceeded"
    assert invoke("pedigree_remember", text="x")["error"]["code"] == "quota_exceeded"
    assert invoke("pedigree_record_action", tool="cat")["error"]["code"] == "quota_exceeded"
    assert invoke("pedigree_check_action", tool="cat", record=True)["error"]["code"] == "quota_exceeded"
    assert (
        client.post("/v1/gate", headers=headers, json={"action": {"tool": "cat"}, "record": True}).status_code
        == 429
    )
    assert client.post("/v1/gate", headers=headers, json={"action": {"tool": "cat"}}).status_code == 200
    assert node_count(db, graph) == 5


def test_zero_growth_edges_and_revocation_barrier(fresh_graph):
    db, tenant, graph = fresh_graph
    policy = QuotaPolicy(tenant, 3)
    record_source(db, graph, tenant, kind="web", id="source", quota=policy)
    remember(db, graph, tenant, id="memory", quota=policy)
    ensure_session(db, graph, tenant, "session", quota=policy)
    corroborate(db, graph, "memory", "source", quota=policy)
    session_read(db, graph, "session", "source", quota=policy)
    before = snapshot(db, graph)
    with pytest.raises(QuotaExceeded):
        revoke(db, graph, tenant, root_id="source", quota=policy)
    assert snapshot(db, graph) == before
    larger = QuotaPolicy(tenant, 4)
    revoke(db, graph, tenant, root_id="source", quota=larger)
    assert node_count(db, graph) == 4
    assert revoke(db, graph, tenant, root_id="source", quota=larger)["idempotent"]
    assert node_count(db, graph) == 4


def _process_writer(settings, tenant, graph, start, results, index):
    db = Db(settings)
    start.wait(10)
    try:
        # Independent interpreter, Redis connection and ContextVar state.
        with admission(db, graph, QuotaPolicy(tenant, 1, 5)) as locked:
            preflight(locked, graph, tenant, [{"op": "memory"}])
            time.sleep(0.10)
            remember(locked, graph, tenant, id=f"proc_{index}")
        results.put("created")
    except QuotaExceeded:
        results.put("quota_exceeded")
    except Exception as exc:
        results.put(type(exc).__name__)


def test_independent_process_competition(fresh_graph):
    db, tenant, graph = fresh_graph
    context = multiprocessing.get_context("spawn")
    start, results = context.Barrier(3), context.Queue()
    workers = [
        context.Process(target=_process_writer, args=(db.settings, tenant, graph, start, results, i))
        for i in range(2)
    ]
    try:
        for worker in workers:
            worker.start()
        start.wait(20)
        outcomes = [results.get(timeout=30) for _ in workers]
        for worker in workers:
            worker.join(10)
            assert worker.exitcode == 0
        assert sorted(outcomes) == ["created", "quota_exceeded"], outcomes
        assert node_count(db, graph) == 1
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(10)
        results.close()
        db.client.connection.delete(lock_key(graph))


def test_ambiguous_write_retains_owner_and_crash_blocks(fresh_graph, monkeypatch):
    db, tenant, graph = fresh_graph
    policy = QuotaPolicy(tenant, 1, 0.01)

    def uncertain(*a, **kw):
        raise Unavailable("synthetic ambiguous database write")

    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(db, "query", uncertain)
            with pytest.raises(Unavailable):
                remember(db, graph, tenant, quota=policy)
        assert db.client.connection.exists(lock_key(graph))
        assert db.client.connection.pttl(lock_key(graph)) == -1
        with pytest.raises(Unavailable, match="writer busy"):
            remember(db, graph, tenant, quota=policy)
        assert node_count(db, graph) == 0
    finally:
        # No DB write was sent by the injected failure and no worker remains active.
        db.client.connection.delete(lock_key(graph))


def _crash_owner(settings, tenant, graph, ready):
    with admission(Db(settings), graph, QuotaPolicy(tenant, 1)):
        ready.set()
        os._exit(0)


def test_process_crash_does_not_expire_mutex(fresh_graph):
    db, tenant, graph = fresh_graph
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    worker = context.Process(target=_crash_owner, args=(db.settings, tenant, graph, ready))
    try:
        worker.start()
        assert ready.wait(20)
        worker.join(10)
        assert worker.exitcode == 0
        assert db.client.connection.pttl(lock_key(graph)) == -1
        with pytest.raises(Unavailable):
            ensure_session(db, graph, tenant, "new_session", quota=QuotaPolicy(tenant, 1, 0.02))
        assert node_count(db, graph) == 0
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(10)
        db.client.connection.delete(lock_key(graph))


def test_reinstate_reserves_ledger_before_status_mutation(fresh_graph):
    from pedigree.engine.revoke import reinstate

    db, tenant, graph = fresh_graph
    policy = QuotaPolicy(tenant, 2)
    record_source(db, graph, tenant, kind="web", id="source", quota=policy)
    revoke(db, graph, tenant, root_id="source", quota=policy)
    before = snapshot(db, graph)
    with pytest.raises(QuotaExceeded):
        reinstate(db, graph, tenant, root_id="source", quota=policy)
    assert snapshot(db, graph) == before
    reinstate(db, graph, tenant, root_id="source", quota=QuotaPolicy(tenant, 3))
    assert node_count(db, graph) == 3


def _process_identity_writer(settings, tenant, graph, barrier, results, op, index):
    db = Db(settings)
    barrier.wait(20)
    try:
        policy = QuotaPolicy(tenant, 1, 5)
        if op == "session":
            ensure_session(db, graph, tenant, "shared_session", quota=policy)
        else:
            record_source(
                db,
                graph,
                tenant,
                kind="web",
                uri="shared_uri",
                content_hash=("b" * 64 if op == "hashed" else None),
                quota=policy,
            )
        results.put("ok")
    except Exception as exc:
        results.put(type(exc).__name__)


@pytest.mark.parametrize("op", ["session", "hashed", "uri"])
def test_independent_process_identity_retry_at_cap(fresh_graph, op):
    db, tenant, graph = fresh_graph
    context = multiprocessing.get_context("spawn")
    barrier, results = context.Barrier(3), context.Queue()
    workers = [
        context.Process(
            target=_process_identity_writer, args=(db.settings, tenant, graph, barrier, results, op, i)
        )
        for i in range(2)
    ]
    try:
        for worker in workers:
            worker.start()
        barrier.wait(20)
        outcomes = [results.get(timeout=30) for _ in workers]
        for worker in workers:
            worker.join(10)
            assert worker.exitcode == 0
        assert outcomes == ["ok", "ok"], outcomes
        assert node_count(db, graph) == 1
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(10)
        results.close()
        db.client.connection.delete(lock_key(graph))


def test_existing_overcap_graph_accepts_only_zero_growth(fresh_graph):
    db, tenant, graph = fresh_graph
    record_source(db, graph, tenant, kind="web", uri="already")
    ensure_session(db, graph, tenant, "existing_session")
    policy = QuotaPolicy(tenant, 1)
    record_source(db, graph, tenant, kind="web", uri="already", quota=policy)
    ensure_session(db, graph, tenant, "existing_session", quota=policy)
    with pytest.raises(QuotaExceeded):
        record_source(db, graph, tenant, kind="web", uri="new", quota=policy)
    assert node_count(db, graph) == 2


def test_nonquota_later_error_preserves_sequential_partial_semantics(quota_public):
    db, _, graph, client, headers, _ = quota_public
    response = client.post(
        "/v1/events",
        headers=headers,
        json={
            "events": [
                {"type": "memory", "id": "first_written"},
                {"type": "memory", "id": "bad_parent", "derived_from": ["absent"]},
            ]
        },
    )
    assert response.status_code == 404, response.text
    assert node_count(db, graph) == 1
    # Deterministic validation failure leaves the mutex releasable.
    assert not db.client.connection.exists(lock_key(graph))


def test_duplicate_explicit_batch_ids_never_return_partial_quota_rejection(quota_public):
    db, tenant, graph, client, headers, _ = quota_public
    # Four existing nodes leave one slot. The duplicate is a conflict, not a new slot.
    for index in range(4):
        remember(db, graph, tenant, id=f"existing_{index}")
    before = snapshot(db, graph)
    response = client.post("/v1/events", headers=headers, json={"events":[
        {"type":"memory", "id":"duplicate"}, {"type":"memory", "id":"duplicate"},
    ]})
    assert response.status_code == 409, response.text
    assert snapshot(db, graph) == before
