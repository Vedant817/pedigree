"""Independent ownership review: local DB sentinel proof + cleanup orchestration spies."""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings, graph_name
from pedigree.db.schema import ensure_schema
from pedigree.engine.ingest import record_source


def load_fixture():
    spec = importlib.util.spec_from_file_location(
        "ownership_review_fixture", Path(__file__).parents[1] / "integration" / "test_isolation_concurrency.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_preexisting_graph_and_registry_survive_fixture_teardown(db):
    """Sentinel exists BEFORE fixture starts; no unrelated graph is enumerated/deleted."""
    module = load_fixture()
    sentinel = "qsent" + uuid.uuid4().hex[:10]
    sentinel_graph = graph_name(sentinel)
    registry = TenantRegistry(db, Settings(pedigree_admin_token="review-local-only"))
    registry.create_tenant(sentinel)
    generator = None
    try:
        ensure_schema(db, sentinel_graph)
        record_source(db, sentinel_graph, sentinel, id="sentinel_source", kind="web", uri="local-sentinel")
        before_record = registry.get_record(sentinel)
        before_nodes = db.ro_query(sentinel_graph, "MATCH(n) RETURN labels(n),properties(n)").result_set
        generator = module.app_client.__wrapped__()
        fixture_db, owned_registry, client = next(generator)
        owned, _ = module._mk_tenant(owned_registry, client)
        owned_graph = graph_name(owned)
        ensure_schema(fixture_db, owned_graph)
        record_source(fixture_db, owned_graph, owned, id="owned_source", kind="web", uri="local-owned")
        generator.close()
        generator = None
        assert sentinel_graph in db.list_graphs()
        assert registry.get_record(sentinel) == before_record
        assert db.ro_query(sentinel_graph, "MATCH(n) RETURN labels(n),properties(n)").result_set == before_nodes
        assert owned_graph not in db.list_graphs()
        assert not db.ro_query(registry.gname, "MATCH(t:Tenant {id:$id}) RETURN t.id", {"id":owned}).result_set
    finally:
        if generator is not None:
            generator.close()
        if sentinel_graph in db.list_graphs():
            db.select(sentinel_graph).delete()
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id":sentinel})


def spy_fixture(monkeypatch, *, status=200, graph_error=False, row_error=False, malformed=False, list_error=False):
    module = load_fixture()
    actions = []

    class SpyDb:
        def select(self, name):
            def delete():
                actions.append(("graph", name))
                if graph_error:
                    raise RuntimeError("review injected missing graph")
            return SimpleNamespace(delete=delete)

        def list_graphs(self):
            if list_error:
                raise RuntimeError("review injected graph-list failure")
            return []

        def query(self, graph, query, params):
            actions.append(("row", params["id"]))
            if row_error:
                raise RuntimeError("review injected registry cleanup failure")

    def list_tenants():
        raise AssertionError("cleanup must never enumerate pre-existing tenants")

    registry = SimpleNamespace(gname="ped:registry", list_tenants=list_tenants)

    def post(url, headers, json):
        def response():
            if malformed:
                raise ValueError("review malformed create response")
            return {"token":"synthetic-review-only"}
        return SimpleNamespace(status_code=status, text="synthetic response", json=response)

    import pedigree.db.client
    monkeypatch.setattr(pedigree.db.client, "Db", lambda settings: SpyDb())
    monkeypatch.setattr(module, "TenantRegistry", lambda db, settings: registry)
    monkeypatch.setattr(module, "create_app", lambda db, settings: None)
    client = SimpleNamespace(post=post, close=lambda:actions.append(("close",None)))
    monkeypatch.setattr(module, "TestClient", lambda app:client)
    generator = module.app_client.__wrapped__()
    next(generator)
    return module, registry, client, generator, actions


def test_no_owned_tenants_means_no_deletes(monkeypatch):
    _, _, _, generator, actions = spy_fixture(monkeypatch)
    generator.close()
    assert actions == [("close",None)]


def test_multiple_successful_creates_delete_only_owned(monkeypatch):
    module, registry, client, generator, actions = spy_fixture(monkeypatch)
    ids = [module._mk_tenant(registry, client)[0] for _ in range(2)]
    generator.close()
    assert {value for action,value in actions if action == "graph"} == {graph_name(tid) for tid in ids}
    assert {value for action,value in actions if action == "row"} == set(ids)
    assert actions[-1] == ("close",None)


def test_failed_creation_cannot_claim_preexisting_tenant(monkeypatch):
    module, registry, client, generator, actions = spy_fixture(monkeypatch, status=409)
    with pytest.raises(AssertionError):
        module._mk_tenant(registry, client)
    assert registry._qa_owned_tenants == set()
    generator.close()
    assert actions == [("close",None)]


def test_successful_creation_with_malformed_response_still_owned(monkeypatch):
    module, registry, client, generator, actions = spy_fixture(monkeypatch, malformed=True)
    with pytest.raises(ValueError):
        module._mk_tenant(registry, client)
    assert len(registry._qa_owned_tenants) == 1
    owned = set(registry._qa_owned_tenants)
    generator.close()
    assert {value for action,value in actions if action == "row"} == owned
    assert actions[-1] == ("close",None)


def test_missing_owned_graph_still_deletes_owned_row(monkeypatch):
    module, registry, client, generator, actions = spy_fixture(monkeypatch, graph_error=True)
    tid, _ = module._mk_tenant(registry, client)
    generator.close()
    assert actions == [("graph",graph_name(tid)), ("row",tid), ("close",None)]


def test_body_failure_still_cleans_owned_and_closes(monkeypatch):
    module, registry, client, generator, actions = spy_fixture(monkeypatch)
    tid, _ = module._mk_tenant(registry, client)
    with pytest.raises(RuntimeError, match="body failure"):
        generator.throw(RuntimeError("review body failure"))
    assert actions == [("graph",graph_name(tid)), ("row",tid), ("close",None)]


def test_registry_cleanup_failure_still_attempts_all_owned_and_closes(monkeypatch):
    module, registry, client, generator, actions = spy_fixture(monkeypatch, row_error=True)
    ids = [module._mk_tenant(registry, client)[0] for _ in range(2)]
    try:
        generator.close()
    except ExceptionGroup:
        pass  # reporting cleanup failure is allowed; skipping other owned work is not
    assert {value for action,value in actions if action == "row"} == set(ids)
    assert actions[-1] == ("close",None)


def test_real_owned_graph_delete_failure_is_reported(db, monkeypatch):
    module = load_fixture()
    generator = module.app_client.__wrapped__()
    fixture_db, registry, client = next(generator)
    owned, _ = module._mk_tenant(registry, client)
    owned_graph = graph_name(owned)
    ensure_schema(fixture_db, owned_graph)
    record_source(fixture_db, owned_graph, owned, id="owned_source", kind="web", uri="local-owned")
    select = fixture_db.select
    closed = []
    close = client.close

    class DeleteFailure:
        def __getattr__(self, key):
            return getattr(select(owned_graph), key)

        def delete(self):
            raise RuntimeError("review injected GRAPH.DELETE failure")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(fixture_db, "select", lambda name:DeleteFailure() if name == owned_graph else select(name))
            patch.setattr(client, "close", lambda:(closed.append(True),close()))
            reported = None
            try:
                generator.close()
            except Exception as exc:
                reported = exc
            assert owned_graph in db.list_graphs(), "fault injection must retain the real owned graph"
            assert closed, "client must close despite graph cleanup failure"
            assert reported is not None, "persisting graph orphan must not be silently accepted"
    finally:
        if owned_graph in db.list_graphs():
            db.select(owned_graph).delete()
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id":owned})


def test_unknown_graph_absence_reports_failure_and_finishes_owned_cleanup(monkeypatch):
    module, registry, client, generator, actions = spy_fixture(monkeypatch, graph_error=True, list_error=True)
    ids = [module._mk_tenant(registry, client)[0] for _ in range(2)]
    with pytest.raises(ExceptionGroup):
        generator.close()
    assert {value for action,value in actions if action == "graph"} == {graph_name(tid) for tid in ids}
    assert {value for action,value in actions if action == "row"} == set(ids)
    assert actions[-1] == ("close",None)
