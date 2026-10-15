"""F-11 gate decisions against the pinned real graph server."""
import pytest

from pedigree.db.schema import check_invariants, node_count
from pedigree.engine.gate import check_action
from pedigree.engine.ingest import (
    corroborate,
    ensure_session,
    record_source,
    remember,
    session_read,
)
from pedigree.engine.revoke import revoke


def shape(fresh_graph, support=None):
    db, tenant, graph = fresh_graph
    record_source(db, graph, tenant, id="bad", kind="rules_file")
    record_source(db, graph, tenant, id="good", kind="file")
    remember(db, graph, tenant, id="m1", derived_from=["bad"])
    remember(db, graph, tenant, id="m2", derived_from=["m1"])
    if support:
        corroborate(db, graph, "m1", "good", by=support)
    revoke(db, graph, tenant, root_id="bad")
    return db, tenant, graph


def gate(fixture, ids, **action):
    db, tenant, graph = fixture
    return check_action(db, graph, {"tool": "Edit", **action}, relied_on=ids, tenant=tenant)


@pytest.mark.parametrize("support", ["human", "scanner"])
def test_preserved_dependent_allows(fresh_graph, support):
    fixture = shape(fresh_graph, support)
    assert gate(fixture, ["m2"], risk="high")["decision"] == "allow"
    result = gate(fixture, ["m1"], risk="high")
    assert result["decision"] == "allow"
    assert result["reasons"][0]["code"] == "preserved_lineage"
    assert check_invariants(fixture[0], fixture[2], fixture[1]) == []


@pytest.mark.parametrize("risk,decision", [("low", "warn"), ("medium", "block"), ("high", "block")])
def test_tainted_risk_matrix(fresh_graph, risk, decision):
    result = gate(shape(fresh_graph), ["m2"], risk=risk)
    assert result["decision"] == decision
    assert result["reasons"][0]["path"] == ["m2", "m1", "bad"]


def test_agent_support_and_descendant_closure(fresh_graph):
    fixture = shape(fresh_graph, "agent")
    assert gate(fixture, ["m1"], risk="medium")["decision"] == "block"
    result = gate(fixture, ["m2"], risk="high")
    assert result["decision"] == "reverify"
    assert result["reasons"][0]["code"] == "preserved_untrusted_support"
    assert result["reasons"][0]["path"] == ["m2", "m1", "bad"]
    assert gate(fixture, ["m2"], risk="medium")["decision"] == "allow"


def test_revoked_and_born_quarantined(fresh_graph):
    db, tenant, graph = shape(fresh_graph)
    remember(db, graph, tenant, id="late", derived_from=["bad"])
    assert gate(fresh_graph, ["late"], risk="medium")["decision"] == "block"
    result = gate(fresh_graph, ["bad"], risk="high")
    assert result["reasons"][0]["path"] == ["bad"]


def test_missing_and_empty_lineage(fresh_graph):
    assert gate(fresh_graph, ["ghost"])["decision"] == "reverify"
    result = gate(fresh_graph, [])
    assert result["decision"] == "allow"
    assert result["reasons"][0]["code"] == "warning:no_lineage"


def test_read_window_floor(fresh_graph):
    db, tenant, graph = shape(fresh_graph)
    ensure_session(db, graph, tenant, "sess")
    session_read(db, graph, "sess", "m2")
    result = check_action(db, graph, {"tool": "Read", "risk": "low"},
                          relied_on=[], session_id="sess")
    assert result["decision"] == "reverify"
    assert result["checked"] == 1


def test_confidentiality_and_integrity(fresh_graph):
    db, tenant, graph = fresh_graph
    record_source(db, graph, tenant, id="secret", kind="web", conf=["team"])
    assert gate(fresh_graph, ["secret"], audience=["local"])["decision"] == "block"
    assert gate(fresh_graph, ["secret"], audience=["team"], risk="low")["decision"] == "allow"
    result = gate(fresh_graph, ["secret"], audience=["team"], risk="high")
    assert result["decision"] == "reverify"
    assert result["would_verify"] == ["secret"]


def test_read_only_and_record_decision(fresh_graph):
    db, tenant, graph = shape(fresh_graph)
    before = db.ro_query(graph, "MATCH (n) RETURN n.id, properties(n) ORDER BY n.id").result_set
    gate(fresh_graph, ["m1"], risk="high")
    after = db.ro_query(graph, "MATCH (n) RETURN n.id, properties(n) ORDER BY n.id").result_set
    assert before == after
    count = node_count(db, graph)
    result = check_action(db, graph, {"tool": "Edit", "risk": "high"},
                          relied_on=["m1"], tenant=tenant, record=True)
    assert node_count(db, graph) == count + 1
    row = db.ro_query(graph, "MATCH (n:Action {id:$id}) RETURN n.decision",
                      {"id": result["action_id"]}).result_set[0]
    assert row == ["block"]


def test_invariant_detects_ok_child_of_bad_parent(fresh_graph):
    db, tenant, graph = shape(fresh_graph)
    db.query(graph, "MATCH (n:Memory {id:'m1'}) SET n.status='ok'")
    assert any("ok node has bad parent" in v for v in check_invariants(db, graph, tenant))
