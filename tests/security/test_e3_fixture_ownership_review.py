"""Local E3 fixture ownership: real sentinel preservation and static cleanup guard."""
from __future__ import annotations

import ast
import importlib.util
import uuid
from functools import partial
from pathlib import Path

import pytest

from pedigree.api.registry import TenantRegistry
from pedigree.config import graph_name
from pedigree.db.schema import ensure_schema
from pedigree.engine.ingest import record_source


def e3_module():
    spec = importlib.util.spec_from_file_location(
        "independent_e3_ownership", Path(__file__).parents[1] / "evals" / "test_e3_scenarios.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sentinel(db):
    tenant = "qe3" + uuid.uuid4().hex[:12]
    graph = graph_name(tenant)
    registry = TenantRegistry(db)
    registry.create_tenant(tenant)  # discard credential; no failure output can expose it
    try:
        ensure_schema(db, graph)
        record_source(db, graph, tenant, id="sentinel", kind="web", uri="local-e3-review")
        record = registry.get_record(tenant)
        nodes = db.ro_query(graph, "MATCH(n) RETURN labels(n),properties(n)").result_set

        def verify():
            assert graph in db.list_graphs(), "pre-existing sentinel graph was deleted"
            assert registry.get_record(tenant) == record
            assert db.ro_query(graph, "MATCH(n) RETURN labels(n),properties(n)").result_set == nodes
        yield verify
        verify()
    finally:
        if graph in db.list_graphs():
            db.select(graph).delete()
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id":tenant})


def assert_owned_absent(db, registry, owned):
    graphs = db.list_graphs()
    for tenant in owned:
        assert graph_name(tenant) not in graphs
        assert not db.ro_query(registry.gname, "MATCH(t:Tenant {id:$id}) RETURN t.id", {"id":tenant}).result_set


def track_creates(monkeypatch, registry):
    owned = []
    create = registry.create_tenant

    def tracked(*args, **kwargs):
        credential = create(*args, **kwargs)
        owned.append(credential.tenant_id)
        return credential
    monkeypatch.setattr(registry, "create_tenant", tracked)
    return owned


@pytest.mark.parametrize("case", ["S1", "S8", "all", "gates", "push"])
def test_sentinel_survives_every_actual_e3_test(case, sentinel, monkeypatch):
    module = e3_module()
    generator = module.boundary.__wrapped__()
    boundary = next(generator)
    db, registry, _, _ = boundary
    owned = track_creates(monkeypatch, registry)
    try:
        if case in ("S1", "S8"):
            module.test_scenario_replay_matches_fixture_expectations(boundary, case)
        elif case == "all":
            module.test_all_scenarios_replay_clean(boundary)
        elif case == "gates":
            module.test_scenario_gate_expectations_hold(boundary)
        else:
            module.test_gate_blocks_a_high_risk_push_on_the_revoked_branch(boundary)
        sentinel()
    finally:
        generator.close()
    assert_owned_absent(db, registry, owned)
    sentinel()


@pytest.mark.parametrize("error", [RuntimeError, AssertionError])
def test_fixture_body_exception_closes_client_preserves_sentinel(error, sentinel):
    module = e3_module()
    generator = module.boundary.__wrapped__()
    boundary = next(generator)
    client = boundary[2]
    with pytest.raises(error):
        generator.throw(error("review injected body failure"))
    assert client.portal is None
    assert client.task.done()
    sentinel()


@pytest.mark.parametrize("case", ["single", "gates", "push", "runner"])
def test_scenario_replay_exception_preserves_sentinel_and_cleans_owned(case, sentinel, monkeypatch):
    module = e3_module()
    generator = module.boundary.__wrapped__()
    boundary = next(generator)
    db, registry, _, _ = boundary
    owned = track_creates(monkeypatch, registry)

    def fail(*args, **kwargs):
        raise RuntimeError("review injected replay failure")
    try:
        if case == "runner":
            import evals.run_e3
            monkeypatch.setattr(evals.run_e3, "replay", fail)
            target = partial(module.test_all_scenarios_replay_clean, boundary)
        else:
            monkeypatch.setattr(module, "replay", fail)
            if case == "single":
                target = partial(module.test_scenario_replay_matches_fixture_expectations, boundary, "S1")
            elif case == "gates":
                target = partial(module.test_scenario_gate_expectations_hold, boundary)
            else:
                target = partial(module.test_gate_blocks_a_high_risk_push_on_the_revoked_branch, boundary)
        with pytest.raises(RuntimeError, match="injected replay failure"):
            target()
    finally:
        generator.close()
    assert owned
    assert_owned_absent(db, registry, owned)
    sentinel()


def test_runner_headers_callback_failure_cleans_created_tenant(sentinel, monkeypatch):
    from evals.run_e3 import run
    module = e3_module()
    generator = module.boundary.__wrapped__()
    db, registry, client, settings = next(generator)
    owned = track_creates(monkeypatch, registry)

    def fail(credential):
        raise RuntimeError("review injected headers callback failure")
    try:
        with pytest.raises(RuntimeError, match="headers callback failure"):
            run(client, db, registry, settings, fail, scenarios=[module.load_scenarios()[0]])
        assert_owned_absent(db, registry, owned)
    finally:
        generator.close()
        # Retained failure repro still cleans ONLY IDs created through this invocation.
        for tenant in owned:
            graph = graph_name(tenant)
            if graph in db.list_graphs():
                db.select(graph).delete()
            db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id":tenant})
    sentinel()


def test_no_fixture_enumerates_all_tenants_for_deletion():
    """Guard dangerous structure, not spelling: any fixture calling list_tenants + delete."""
    violations = []
    for path in Path(__file__).parents[1].rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = [ast.unparse(decorator) for decorator in function.decorator_list]
            if not any("fixture" in decorator for decorator in decorators):
                continue
            calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
            enumerates = any(isinstance(call.func, ast.Attribute) and call.func.attr == "list_tenants"
                             for call in calls)
            deletes = any((isinstance(call.func, ast.Attribute) and call.func.attr == "delete")
                          or any(isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                                 and "DELETE" in arg.value.upper() for arg in call.args)
                          for call in calls)
            if enumerates and deletes:
                violations.append(f"{path.name}:{function.lineno}:{function.name}")
    assert not violations, violations


def test_session_guard_detects_deleted_unrelated_sentinel(db, sentinel, monkeypatch):
    """Exercise the guard's failure path using ONLY its newly created self-test tenant."""
    spec = importlib.util.spec_from_file_location(
        "ownership_guard_self_review", Path(__file__).parents[1] / "conftest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "Db", lambda:db)
    created = []
    create = TenantRegistry.create_tenant

    def tracked(registry, *args, **kwargs):
        credential = create(registry, *args, **kwargs)
        created.append(credential.tenant_id)
        return credential
    monkeypatch.setattr(TenantRegistry, "create_tenant", tracked)
    generator = module.db.__wrapped__()
    next(generator)
    assert len(created) == 1
    graph = graph_name(created[0])
    try:
        db.select(graph).delete()  # exact self-test-owned sentinel, never another tenant
        with pytest.raises(AssertionError, match="session ownership sentinel graph was deleted"):
            next(generator)
        registry = TenantRegistry(db)
        assert not db.ro_query(registry.gname, "MATCH(t:Tenant {id:$id}) RETURN t.id", {"id":created[0]}).result_set
        sentinel()
    finally:
        generator.close()
        if graph in db.list_graphs():
            db.select(graph).delete()
        db.query(graph_name("registry"), "MATCH(t:Tenant {id:$id}) DELETE t", {"id":created[0]})
