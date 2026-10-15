"""E3 - the authored scenarios, replayed through the HTTP API on a real FalkorDB."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from evals.run_e3 import assert_expected, gate_verdict, replay, run
from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings
from pedigree.db.client import Db
from pedigree.demo import load_scenarios


@pytest.fixture
def boundary():
    settings = Settings(pedigree_admin_token="e3-test-operator")
    db = Db(settings)
    registry = TenantRegistry(db, settings)
    client = TestClient(create_app(db, settings))
    yield db, registry, client, settings
    for record in registry.list_tenants():
        try:
            db.select(f"ped:{record.tenant_id}").delete()
        except Exception:  # noqa: BLE001 - already gone
            pass
        db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": record.tenant_id})


def _render(db, registry, settings, client):
    def headers_for(credential):
        return {"Authorization": "Bearer " + credential.token,
                "X-Admin-Token": settings.pedigree_admin_token}
    return run(client, db, registry, settings, headers_for)


@pytest.mark.parametrize("scenario_id", ["S1", "S8"])
def test_scenario_replay_matches_fixture_expectations(boundary, scenario_id):
    db, registry, client, settings = boundary
    scenarios = [s for s in load_scenarios() if s["id"] == scenario_id]
    assert scenarios
    from pedigree.config import graph_name

    scenario = scenarios[0]
    credential = registry.create_tenant("e3" + scenario_id.lower() + str(abs(hash(scenario_id)) % 10 ** 6))
    gname = graph_name(credential.tenant_id)
    headers = {"Authorization": "Bearer " + credential.token,
               "X-Admin-Token": settings.pedigree_admin_token}
    try:
        replay(scenario, client, headers)
        assert assert_expected(scenario, db, gname) == []
    finally:
        db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": credential.tenant_id})
        try:
            db.select(gname).delete()
        except Exception:  # noqa: BLE001
            pass


def test_all_scenarios_replay_clean(boundary):
    db, registry, client, settings = boundary
    failures = _render(db, registry, settings, client)
    assert failures == [], failures


def test_gate_blocks_a_high_risk_push_on_the_revoked_branch(boundary):
    db, registry, client, settings = boundary
    scenario = next(s for s in load_scenarios() if s["id"] == "S1")
    credential = registry.create_tenant("e3gate" + str(abs(hash("gate")) % 10 ** 6))
    from pedigree.config import graph_name

    gname = graph_name(credential.tenant_id)
    headers = {"Authorization": "Bearer " + credential.token,
               "X-Admin-Token": settings.pedigree_admin_token}
    tainted = next((n["id"] for n in scenario["nodes"]
                    if n["type"] == "memory"
                    and scenario["root_id"] in n.get("derived_from", [])), None)
    try:
        replay(scenario, client, headers)
        assert tainted is not None
        verdict = gate_verdict(scenario, client, headers, node_id=tainted,
                               tool="Bash", risk="high", effect="irreversible")
        assert verdict in ("block", "reverify"), verdict
        unknown = gate_verdict(scenario, client, headers, node_id="never_recorded_id",
                               tool="Read", risk="low", effect="reversible")
        assert unknown == "reverify"
    finally:
        db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": credential.tenant_id})
        try:
            db.select(gname).delete()
        except Exception:  # noqa: BLE001
            pass
