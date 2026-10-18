"""Independent partitions verify weak-component summaries on real FalkorDB."""
import pytest

from pedigree.engine.components import weak_components


@pytest.mark.parametrize("edges,expected", [
    ([], [1, 1, 1, 1]),
    ([(0, 1), (2, 3)], [2, 2]),
    ([(0, 1), (2, 1), (2, 3)], [4]),
    ([(0, 1), (1, 0)], [2, 1, 1]),
])
def test_components_partition_and_direction_independence(fresh_graph, edges, expected):
    db, _, graph = fresh_graph
    db.query(graph, "UNWIND range(0,3) AS i CREATE (:Node:Source {id:toString(i)})")
    db.query(graph, "UNWIND $edges AS e MATCH(a:Node {id:toString(e[0])}),"
             "(b:Node {id:toString(e[1])}) MERGE(a)-[:DERIVED_FROM]->(b)", {"edges": edges})
    result = weak_components(db, graph)
    assert [c["nodes"] for c in result["components"]] == expected
    assert sum(c["nodes"] for c in result["components"]) == 4
    assert result["truncated"] is False


def test_components_limit_is_explicit_and_empty_is_not_failure(fresh_graph):
    db, _, graph = fresh_graph
    assert weak_components(db, graph)["components"] == []
    db.query(graph, "UNWIND range(0,3) AS i CREATE (:Node:Source {id:toString(i)})")
    result = weak_components(db, graph, limit=2)
    assert len(result["components"]) == 2
    assert result["truncated"] is True


def test_metadata_cannot_bridge_otherwise_disconnected_lineage(fresh_graph):
    db, _, graph = fresh_graph
    db.query(graph, "CREATE(a:Node:Action {id:'a'}), (b:Node:Action {id:'b'}),"
             "(s:Node:Session {id:'session'}), (a)-[:DERIVED_FROM]->(s),"
             "(b)-[:DERIVED_FROM]->(s)")
    result = weak_components(db, graph)
    assert sorted(component["nodes"] for component in result["components"]) == [1, 1]


def test_components_query_failure_propagates(fresh_graph, monkeypatch):
    from pedigree.errors import Unavailable

    db, _, graph = fresh_graph
    def unavailable(*args, **kwargs):
        raise Unavailable("database unavailable")
    monkeypatch.setattr(db, "ro_query", unavailable)
    with pytest.raises(Unavailable):
        weak_components(db, graph)


def test_component_endpoint_authentication_and_scoped_connection(fresh_graph, monkeypatch):
    from fastapi.testclient import TestClient

    from pedigree.api.app import create_app
    from pedigree.api.registry import TenantRegistry

    db, tenant, graph = fresh_graph
    registry = TenantRegistry(db)
    credential = registry.create_tenant(tenant)
    try:
        with TestClient(create_app(db, db.settings)) as client:
            assert client.get("/v1/audit/components").status_code == 401
            headers = {"Authorization": "Bearer " + credential.agent_token}
            assert client.post("/v1/sources", headers=headers,
                               json={"kind": "file", "uri": "captured-file", "id": "s"}).status_code == 200
            original = db.select
            def registry_only(gname):
                assert gname != graph, "component query used privileged DB connection"
                return original(gname)
            with monkeypatch.context() as patch:
                patch.setattr(db, "select", registry_only)
                result = client.get("/v1/audit/components", headers=headers)
            assert result.status_code == 200, result.text
            assert result.json()["components"][0]["nodes"] == 1
            assert result.json()["trace"][0]["op"] == "audit.components"
            assert client.get("/v1/audit/components?limit=101", headers=headers).status_code == 422
    finally:
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})
