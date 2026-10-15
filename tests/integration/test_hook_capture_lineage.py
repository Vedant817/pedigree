"""Capture-to-gate lineage through the real event boundary."""
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings
from pedigree.engine.ingest import record_source
from pedigree.engine.revoke import revoke


def test_hook_action_inherits_read_window(fresh_graph):
    db, tenant, graph = fresh_graph
    settings = Settings()
    registry = TenantRegistry(db, settings)
    token = registry.create_tenant(tenant).token
    client = TestClient(create_app(db, settings))
    headers = {"Authorization": "Bearer " + token}
    try:
        run_capture(db, tenant, graph, client, headers)
    finally:
        db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": tenant})


def run_capture(db, tenant, graph, client, headers):
    record_source(db, graph, tenant, id="source", kind="file")
    payload = {"runtime": "claude-code", "session_id": "captured", "events": [
        {"type": "session"}, {"type": "read", "node_id": "source"},
        {"type": "action", "tool": "Edit", "summary": "write file", "id": "write"},
    ]}
    response = client.post("/v1/events", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    rows = db.ro_query(graph, "MATCH (:Action {id:'write'})-[d:DERIVED_FROM]->(p) RETURN p.id, d.via").result_set
    assert rows == [["source", "hook"]]
    revoke(db, graph, tenant, root_id="source")
    response = client.post("/v1/gate", headers=headers, json={
        "action": {"tool": "Bash", "summary": "git push"}, "relied_on": ["write"]})
    assert response.json()["decision"] == "block", response.text
