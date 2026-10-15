"""E3 - replay the authored scenarios through the HTTP API and assert the expected sets
(docs/03 section 5): contamination, preservation, affected actions, irreversible actions and
gate verdicts. TestClient drives the same app/code path as HTTP; `python evals/run_e3.py` drives
a live uvicorn service instead.
"""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings, graph_name
from pedigree.db.client import Db
from pedigree.demo import load_scenarios

ADMIN = "e3-operator"


def _fixture_headers(credential, client: TestClient, operator: str | None):
    headers = {"Authorization": "Bearer " + credential.token}
    if operator:
        headers["X-Admin-Token"] = operator
    return headers


def replay(scenario: dict, client: TestClient, headers: dict) -> dict:
    """POST the fixture's nodes through /v1/events and its corroborations through
    /v1/corroborate (operator credential), then revoke the root and return what the API reports."""
    session = f"e3-{scenario['id'].lower()}"
    # a capture session starts first: actions link to their session (that is how the real
    # adapters behave), and an action whose session does not exist is refused
    events: list[dict] = [{"type": "ensure_session", "session_id": session}]
    for node in scenario["nodes"]:
        kind = node["type"]
        base = {"id": node["id"]}
        if kind == "source":
            events.append({**base, "type": "source", "source_kind": node["kind"],
                           "uri": node.get("uri"), "title": node.get("title"),
                           "conf": node.get("conf", [])})
        elif kind == "memory":
            events.append({**base, "type": "memory", "text": node.get("text", ""),
                           "derived_from": node.get("derived_from", []),
                           "corroborated_by": node.get("corroborated_by", [])})
        elif kind == "action":
            events.append({**base, "type": "action", "tool": node["tool"],
                           "summary": node.get("summary", ""),
                           "relied_on": node.get("relied_on", []),
                           "effect": node.get("effect"), "risk": node.get("risk"),
                           "artifacts": node.get("artifacts", [])})
    response = client.post("/v1/events", headers=headers,
                           json={"runtime": "generic", "session_id": session, "events": events})
    assert response.status_code == 200, response.text
    created = response.json()["created"]

    # support attestations go through the operator credential (ADR-008)
    for support in scenario.get("corroborations", []):
        r = client.post("/v1/corroborate", headers=headers, json={
            "memory_id": support["memory_id"], "source_id": support["source_id"],
            "by": support.get("by", "human")})
        assert r.status_code == 200, r.text

    revoke = client.post("/v1/revoke", headers=headers,
                         json={"root_id": scenario["root_id"], "reason": "synthetic scenario"})
    assert revoke.status_code == 200, revoke.text
    return {"created": created, "revoke": revoke.json()}


def gate_verdict(scenario: dict, client: TestClient, headers: dict, node_id: str, tool: str,
                 risk: str, effect: str) -> str:
    body = {"action": {"tool": tool, "summary": scenario.get("title", "gate probe"),
                       "effect": effect, "risk": risk}, "relied_on": [node_id]}
    response = client.post("/v1/gate", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()["decision"]


def assert_expected(scenario: dict, db: Db, gname: str) -> list[str]:
    """Compare the replay against the fixture's expected statuses."""
    from pedigree.engine.ingest import get_node_statuses

    expected = scenario.get("expected_after_revoke", {})
    actual = get_node_statuses(db, gname, list(expected))
    problems = [f"{node}: expected {want}, got {actual.get(node)}"
                for node, want in expected.items() if actual.get(node) != want]
    return problems


def run(client: TestClient, db: Db, registry: TenantRegistry, settings: Settings,
        headers_for, scenarios=None) -> list[str]:
    failures: list[str] = []
    for scenario in (scenarios if scenarios is not None else load_scenarios()):
        tenant = "e3" + uuid.uuid4().hex[:9]
        credential = registry.create_tenant(tenant)
        gname = graph_name(tenant)
        db.select(gname).delete() if False else None
        headers = headers_for(credential)
        try:
            replay(scenario, client, headers)
            problems = assert_expected(scenario, db, gname)
            if problems:
                failures.extend(f"{scenario['id']}: {p}" for p in problems)
            # gate probes: a high-risk push relying on the tainted branch must not be allowed
            root = scenario["root_id"]
            verdict = gate_verdict(scenario, client, headers,
                                   node_id=next((m for m, ps in
                                                 _parents(scenario).items() if root in ps), root),
                                   tool="Bash", risk="high", effect="irreversible")
            if verdict == "allow":
                failures.append(f"{scenario['id']}: gate allowed a high-risk push built on the "
                                f"revoked branch")
        finally:
            db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": tenant})
            try:
                db.select(gname).delete()
            except Exception:  # noqa: BLE001 - already gone
                pass
    return failures


def _parents(scenario: dict) -> dict[str, list[str]]:
    parents: dict[str, list[str]] = {}
    for node in scenario["nodes"]:
        parents[node["id"]] = node.get("derived_from", node.get("relied_on", []))
    return parents


def main() -> int:
    settings = Settings(pedigree_admin_token=ADMIN)
    db = Db(settings)
    registry = TenantRegistry(db, settings)
    client = TestClient(create_app(db, settings))

    def headers_for(credential):
        return _fixture_headers(credential, client, ADMIN)

    failures = run(client, db, registry, settings, headers_for)
    if failures:
        print("[e3] FAIL")
        for failure in failures:
            print("  -", failure)
        return 1
    print("[e3] PASS: every authored scenario reproduced through the HTTP API "
          "(contamination, preservation, gate)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
