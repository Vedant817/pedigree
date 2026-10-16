"""Fixture ownership checks, with spies only for cleanup orchestration (not graph logic)."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_isolation_fixture_never_deletes_preexisting_tenant(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "isolation_fixture_review", Path(__file__).parents[1] / "integration" / "test_isolation_concurrency.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    removed_graphs, removed_rows = [], []
    records = {"preexisting": SimpleNamespace(tenant_id="preexisting")}

    class FakeDb:
        def select(self, graph):
            return SimpleNamespace(delete=lambda: removed_graphs.append(graph))

        def query(self, graph, cypher, params):
            removed_rows.append(params["id"])

    registry = SimpleNamespace(gname="ped:registry", list_tenants=lambda: list(records.values()))

    def post(url, headers, json):
        tid = json["id"]
        records[tid] = SimpleNamespace(tenant_id=tid)
        return SimpleNamespace(status_code=200, text="", json=lambda: {"token": "synthetic"})

    import pedigree.db.client
    monkeypatch.setattr(pedigree.db.client, "Db", lambda settings: FakeDb())
    monkeypatch.setattr(module, "TenantRegistry", lambda db, settings: registry)
    monkeypatch.setattr(module, "create_app", lambda db, settings: None)
    monkeypatch.setattr(module, "TestClient", lambda app: SimpleNamespace(post=post, close=lambda: None))
    generator = module.app_client.__wrapped__()
    _, reg, client = next(generator)
    owned, _ = module._mk_tenant(reg, client)
    with pytest.raises(StopIteration):
        next(generator)
    assert removed_rows == [owned]
    assert removed_graphs == ["ped:" + owned]


def test_e3_fixture_never_deletes_preexisting_tenant(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "e3_fixture_review", Path(__file__).parents[1] / "evals" / "test_e3_scenarios.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    removed = []
    closed = []
    registry = SimpleNamespace(gname="ped:registry", list_tenants=lambda: [SimpleNamespace(tenant_id="preexisting")])
    db = SimpleNamespace(select=lambda graph: SimpleNamespace(delete=lambda: removed.append(graph)),
                         query=lambda *args: removed.append(args))
    class Client:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            closed.append(True)
        def close(self):
            closed.append(True)
    monkeypatch.setattr(module, "Db", lambda settings: db)
    monkeypatch.setattr(module, "TenantRegistry", lambda db, settings: registry)
    monkeypatch.setattr(module, "create_app", lambda db, settings: None)
    monkeypatch.setattr(module, "TestClient", lambda app: Client())
    generator = module.boundary.__wrapped__()
    next(generator)
    with pytest.raises(StopIteration):
        next(generator)
    assert removed == []
    assert closed == [True]
