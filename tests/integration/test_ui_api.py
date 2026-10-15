from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings
from pedigree.engine.ingest import record_action, record_source, remember


def test_static_workspace_is_served(db):
    client = TestClient(create_app(db, Settings()))
    r = client.get("/")
    assert r.status_code == 200
    assert "Lineage workspace" in r.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/vendor/cytoscape.min.js").status_code == 200


def test_graph_feed_real_bounded_and_isolated(fresh_graph):
    db, tenant, graph = fresh_graph
    settings = Settings()
    registry = TenantRegistry(db, settings)
    credential = registry.create_tenant(tenant)
    client = TestClient(create_app(db, settings))
    headers = {"Authorization": "Bearer " + credential.token}
    try:
        record_source(db, graph, tenant, id="src", kind="file", title="Own document")
        remember(db, graph, tenant, id="mem", text="DO NOT EXPOSE RAW MEMORY", derived_from=["src"])
        record_action(db, graph, tenant, id="act", tool="Bash", relied_on=["mem"], summary="private command")
        assert client.get("/v1/graph/view").status_code == 401
        r = client.get("/v1/graph/view", headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert {n["id"] for n in data["nodes"]} == {"src", "mem", "act"}
        assert len(data["edges"]) == 2
        assert data["truncated"] is False
        assert "DO NOT EXPOSE RAW MEMORY" not in r.text and "private command" not in r.text
        bounded = client.get("/v1/graph/view?limit=1", headers=headers).json()
        assert len(bounded["nodes"]) == 1 and bounded["truncated"] is True
        returned = {n["id"] for n in bounded["nodes"]}
        assert all(e["from"] in returned and e["to"] in returned for e in bounded["edges"])
        assert client.get("/v1/graph/view?limit=1001", headers=headers).status_code == 422
        assert client.get("/v1/graph/view?limit=0", headers=headers).status_code == 422
    finally:
        db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": tenant})
