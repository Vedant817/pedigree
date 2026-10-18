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


def test_components_query_failure_propagates(fresh_graph, monkeypatch):
    from pedigree.errors import Unavailable

    db, _, graph = fresh_graph
    def unavailable(*args, **kwargs):
        raise Unavailable("database unavailable")
    monkeypatch.setattr(db, "ro_query", unavailable)
    with pytest.raises(Unavailable):
        weak_components(db, graph)
