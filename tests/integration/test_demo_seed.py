"""F-10 synthetic scenarios on actual FalkorDB, never recorded runtime evidence."""
import importlib.util
import json
from pathlib import Path

import pytest

from pedigree.config import graph_name
from pedigree.db.schema import check_invariants, node_count
from pedigree.demo import load_scenarios, seed_scenarios
from pedigree.engine.blame import blame
from pedigree.engine.gate import check_action
from pedigree.engine.ingest import get_node_statuses, record_source
from pedigree.engine.revoke import revoke
from pedigree.errors import InvalidArgument


def test_scenario_dir_env_override(tmp_path, monkeypatch):
    scenario_dir = tmp_path / "fixtures"
    scenario_dir.mkdir()
    (scenario_dir / "S1.json").write_text('{"id": "S1"}', encoding="utf-8")
    monkeypatch.setenv("PEDIGREE_SCENARIOS_DIR", str(scenario_dir))
    assert load_scenarios() == [{"id": "S1"}]


def test_scenario_dir_finds_container_working_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("PEDIGREE_SCENARIOS_DIR", raising=False)
    nested = tmp_path / "demo" / "scenarios"
    nested.mkdir(parents=True)
    (nested / "S1.json").write_text('{"id": "S1"}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert load_scenarios() == [{"id": "S1"}]


def test_scenario_dir_falls_back_to_source_tree(tmp_path, monkeypatch):
    monkeypatch.delenv("PEDIGREE_SCENARIOS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert load_scenarios()  # the checkout/editable-install candidate still resolves


def test_seed_is_repeatable_without_touching_unrelated_data(fresh_graph):
    db, tenant, gname = fresh_graph
    record_source(db, gname, tenant, kind="file", id="unrelated", uri="private.txt")
    first = seed_scenarios(db, tenant)
    total = node_count(db, gname)
    second = seed_scenarios(db, tenant)
    assert first["created"] > 0
    assert second["created"] == 0
    assert node_count(db, gname) == total
    assert get_node_statuses(db, gname, ["unrelated"]) == {"unrelated": "ok"}
    assert check_invariants(db, gname, expected_tenant=tenant) == []


@pytest.mark.parametrize("scenario_id", ["S1", "S7", "S8"])
def test_scenario_manifest_matches_real_revoke(fresh_graph, scenario_id):
    db, tenant, gname = fresh_graph
    seed_scenarios(db, tenant)
    scenario = next(s for s in load_scenarios() if s["id"] == scenario_id)
    result = revoke(db, gname, tenant, root_id=scenario["root_id"], reason="synthetic demo",
                    kind=scenario.get("revoke_kind", "revoke"))
    assert result["kind"] == scenario.get("revoke_kind", "revoke")
    assert get_node_statuses(db, gname, list(scenario["expected_after_revoke"])) == scenario["expected_after_revoke"]
    assert sorted(a["id"] for a in result["irreversible"]) == scenario["expected_irreversible"]
    if scenario.get("expected_revisit") is not None:
        assert sorted(a["id"] for a in result["actions"]) == sorted(scenario["expected_revisit"])
    if scenario_id == "S1":
        explanation = blame(db, gname, "demo_s1_push")
        root = next(root for root in explanation["roots"] if root["id"] == scenario["root_id"])
        assert root["path"] == scenario["expected_push_blame_path"]
    assert check_invariants(db, gname, expected_tenant=tenant) == []
    before = node_count(db, gname)
    assert seed_scenarios(db, tenant)["created"] == 0
    assert node_count(db, gname) == before
    assert get_node_statuses(db, gname, list(scenario["expected_after_revoke"])) == scenario["expected_after_revoke"]
    if scenario_id == "S8":
        gate = check_action(db, gname, {"tool": "Edit", "risk": "medium", "effect": "reversible"},
                            relied_on=["demo_s8_dependent"])
        assert gate["decision"] == "allow"
        high = check_action(db, gname, {"tool": "git push", "risk": "high", "effect": "irreversible"},
                            relied_on=["demo_s8_dependent"])
        assert high["decision"] == "reverify"
        assert any(reason["code"] == "untrusted_influence" for reason in high["reasons"])


def test_seed_invalid_tenant_rejected_before_db_use():
    with pytest.raises(InvalidArgument):
        seed_scenarios(None, "user:other")


def test_fixture_ids_are_disjoint_and_synthetic():
    scenarios = load_scenarios()
    ids = [node["id"] for scenario in scenarios for node in scenario["nodes"]]
    assert len(ids) == len(set(ids))
    assert all(scenario["synthetic"] is True for scenario in scenarios)
    assert graph_name("demo") == "ped:demo"


def test_registry_credential_is_saved_once_and_reused(fresh_graph, tmp_path, capsys):
    from pedigree.api.registry import TenantRegistry

    file = Path(__file__).resolve().parents[2] / "scripts" / "seed_demo.py"
    spec = importlib.util.spec_from_file_location("seed_demo", file)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    db, tenant, _gname = fresh_graph
    registry = TenantRegistry(db)
    try:
        credential_file = script.ensure_demo_tenant(registry, tenant, tmp_path)
        original = credential_file.read_bytes()
        credential = json.loads(original)
        assert registry.resolve(credential["token"]).tenant_id == tenant
        assert script.ensure_demo_tenant(registry, tenant, tmp_path) == credential_file
        assert credential_file.read_bytes() == original
        credential_file.unlink()
        assert script.ensure_demo_tenant(registry, tenant, tmp_path) is None
        assert registry.resolve(credential["token"]).tenant_id == tenant
        assert credential["token"] not in capsys.readouterr().out
    finally:
        db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": tenant}, op="test.cleanup")


def test_stale_local_credential_is_replaced_not_fatal(fresh_graph, tmp_path):
    """A local credential file for a tenant that no longer exists blocks re-seeding (devex fix:
    the documented quick-start died on `FileExistsError`); a file whose token still resolves is
    never overwritten."""
    from pedigree.api.registry import TenantRegistry

    file = Path(__file__).resolve().parents[2] / "scripts" / "seed_demo.py"
    spec = importlib.util.spec_from_file_location("seed_demo", file)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    db, tenant, _gname = fresh_graph
    registry = TenantRegistry(db)
    stale = tmp_path / f"demo-{tenant}.json"
    stale.write_text(json.dumps({"tenant": tenant, "token": "ped_dead_token"}) + "\n", encoding="utf-8")
    # an unreadable file is not "stale": it is left alone and the create refuses
    unreadable = tmp_path / "demo-unreadabletenant.json"
    unreadable.write_text("not json at all", encoding="utf-8")
    with pytest.raises(FileExistsError):
        script.ensure_demo_tenant(registry, "unreadabletenant", tmp_path)
    assert unreadable.read_text(encoding="utf-8") == "not json at all"
    try:
        credential_file = script.ensure_demo_tenant(registry, tenant, tmp_path)
        assert credential_file == stale
        credential = json.loads(credential_file.read_text(encoding="utf-8"))
        assert credential["token"] != "ped_dead_token"
        assert registry.resolve(credential["token"]).tenant_id == tenant
        # a live credential is never overwritten
        assert script.ensure_demo_tenant(registry, tenant, tmp_path) == credential_file
        assert json.loads(credential_file.read_text(encoding="utf-8"))["token"] == credential["token"]
    finally:
        db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": tenant}, op="test.cleanup")
