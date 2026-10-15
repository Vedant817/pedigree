"""Independent real-database F-10 probes. Never touch the shared demo tenant."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pedigree.api.registry import TenantRegistry
from pedigree.demo import seed_scenarios
from pedigree.engine.gate import check_action
from pedigree.engine.ingest import corroborate, record_source, remember
from pedigree.engine.revoke import revoke
from pedigree.errors import Conflict


def script_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "seed_demo.py"
    spec = importlib.util.spec_from_file_location("qa_seed_demo", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_qa_existing_fixture_id_collision_refuses_without_changes(fresh_graph):
    db, tenant, graph = fresh_graph
    record_source(db, graph, tenant, id="private_root", kind="file")
    remember(db, graph, tenant, id="demo_s8_supported", text="Existing user content",
             derived_from=["private_root"])
    before = db.ro_query(graph, "MATCH (n) RETURN n.id, properties(n) ORDER BY n.id").result_set
    with pytest.raises(Conflict):
        seed_scenarios(db, tenant)
    assert db.ro_query(graph, "MATCH (n) RETURN n.id, properties(n) ORDER BY n.id").result_set == before


def test_qa_existing_credential_path_never_overwritten(fresh_graph, tmp_path):
    db, tenant, _ = fresh_graph
    registry = TenantRegistry(db)
    destination = tmp_path / f"demo-{tenant}.json"
    destination.write_text("do not overwrite", encoding="utf-8")
    with pytest.raises(FileExistsError):
        script_module().ensure_demo_tenant(registry, tenant, tmp_path)
    assert destination.read_text(encoding="utf-8") == "do not overwrite"
    assert all(record.tenant_id != tenant for record in registry.list_tenants())


def test_qa_revoked_registry_tenant_not_reactivated(fresh_graph, tmp_path):
    db, tenant, _ = fresh_graph
    registry = TenantRegistry(db)
    try:
        registry.create_tenant(tenant)
        registry.revoke_tenant(tenant)
        with pytest.raises(ValueError, match="revoked"):
            script_module().ensure_demo_tenant(registry, tenant, tmp_path)
        assert registry.get_record(tenant).status == "revoked"
        assert not (tmp_path / f"demo-{tenant}.json").exists()
    finally:
        db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": tenant})


def test_qa_revoke_both_scenarios_then_reseed_retains_gate_results(fresh_graph):
    db, tenant, graph = fresh_graph
    seed_scenarios(db, tenant)
    for root in ("demo_s1_web", "demo_s8_web"):
        revoke(db, graph, tenant, root_id=root)
    before = db.ro_query(graph, "MATCH (n) RETURN n.id, n.status ORDER BY n.id").result_set
    for _ in range(3):
        assert seed_scenarios(db, tenant)["created"] == 0
    assert db.ro_query(graph, "MATCH (n) RETURN n.id, n.status ORDER BY n.id").result_set == before
    assert check_action(db, graph, {"tool": "Edit", "risk": "medium"},
                        relied_on=["demo_s8_dependent"])["decision"] == "allow"
    assert check_action(db, graph, {"tool": "Bash", "summary": "git push"},
                        relied_on=["demo_s8_dependent"])["decision"] == "reverify"
    assert check_action(db, graph, {"tool": "Bash", "summary": "git commit"},
                        relied_on=["demo_s1_push"])["decision"] == "block"


def test_qa_reseed_does_not_restore_changed_support_authority(fresh_graph):
    db, tenant, graph = fresh_graph
    seed_scenarios(db, tenant)
    corroborate(db, graph, "demo_s8_supported", "demo_s8_docs", by="agent")
    revoke(db, graph, tenant, root_id="demo_s8_web")
    action = {"tool": "Edit", "risk": "medium"}
    # Corroboration is write-once-then-upgrade (ADR-008): an agent call cannot replace a
    # human attestation, so the human-attested branch still passes the gate.
    before = check_action(db, graph, action, relied_on=["demo_s8_supported"])["decision"]
    assert before == "allow"
    seed_scenarios(db, tenant)
    after = check_action(db, graph, action, relied_on=["demo_s8_supported"])["decision"]
    print(f"RESEED support-author change: gate_before={before}; gate_after={after}")
    assert after == before
    by = db.ro_query(graph, "MATCH ()-[c:CORROBORATED_BY]->() RETURN c.by").result_set[0][0]
    assert by == "human"


def test_qa_cli_credential_not_in_output_and_ignored(fresh_graph):
    db, tenant, graph = fresh_graph
    registry = TenantRegistry(db)
    repo = Path(__file__).resolve().parents[2]
    credential_path = repo / "scratch" / f"demo-{tenant}.json"
    assert not credential_path.exists()
    env = {**os.environ, "PEDIGREE_DEMO_TENANT": tenant}
    try:
        command = [sys.executable, str(repo / "scripts" / "seed_demo.py")]
        first = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20, check=True)
        original = credential_path.read_bytes()
        token = json.loads(original)["token"]
        assert token not in first.stdout + first.stderr
        assert '"created": 11' in first.stdout
        second = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20, check=True)
        assert token not in second.stdout + second.stderr
        assert '"created": 0' in second.stdout
        assert credential_path.read_bytes() == original
        ignored = subprocess.run(["git", "check-ignore", str(credential_path)],
                                 cwd=repo, capture_output=True, text=True, check=True)
        assert ignored.returncode == 0
        print("CLI seed: created=11 then 0; token absent stdout/stderr; credential unchanged; git check-ignore exit=0")
    finally:
        credential_path.unlink(missing_ok=True)
        db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": tenant})
