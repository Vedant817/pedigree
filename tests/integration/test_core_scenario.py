"""AT0.2 - the verified core scenario, ported from tech/examples/py/12_pedigree_core.py.

Scenario S1+S8 shape: an untrusted web page poisons m1 and m2; m2 is independently
corroborated by a trusted file, so it must be `preserved` while its dependents survive;
a commit and a push depend on the tainted branch.
"""

from __future__ import annotations

import pytest

from pedigree.db.queries import Q_REVOCATION_LATEST
from pedigree.db.schema import check_invariants
from pedigree.engine.ingest import (
    artifact_lookup,
    corroborate,
    get_node_statuses,
    record_action,
    record_source,
    remember,
)
from pedigree.engine.revoke import reinstate, report, resume_incomplete, revoke
from pedigree.errors import Conflict, InvalidArgument, NotFoundInGraph, TooLarge


def _build(db, tenant, gname):
    """Same construction as the verified prototype: each node is created ONCE.

    (The prototype used add_node + separate derive() calls; here parents are passed
    to remember()/record_action() at creation time - creating a node twice would
    violate the unique constraint.)
    """
    record_source(db, gname, tenant, kind="web", id="s_web", uri="http://evil.example/x", title="page")
    record_source(db, gname, tenant, kind="file", id="s_doc", uri="docs/README.md")
    record_source(db, gname, tenant, kind="file", id="s_hr", uri="hr/salaries.csv", conf=["hr"])
    remember(db, gname, tenant, text="web summary", id="m1", derived_from=["s_web"])
    remember(db, gname, tenant, text="web claim corroborated", id="m2", derived_from=["s_web"],
             corroborated_by=["s_doc"])
    remember(db, gname, tenant, text="joined conclusion", id="m3", derived_from=["m1", "m2"])
    remember(db, gname, tenant, text="depends on preserved", id="m4", derived_from=["m2"])
    remember(db, gname, tenant, text="from our docs", id="m5", derived_from=["s_doc"])
    remember(db, gname, tenant, text="deep conclusion", id="m6", derived_from=["m3"])
    record_action(db, gname, tenant, tool="git commit", summary="commit the change", id="a_commit",
                  relied_on=["m3"], effect="reversible", risk="medium", artifacts=["abc123"])
    record_action(db, gname, tenant, tool="git push", summary="push to origin", id="a_push",
                  relied_on=["m6", "m5"], effect="irreversible", risk="high", via="session_read")


EXPECTED_AFTER_REVOKE = {
    "s_web": "revoked",
    "s_doc": "ok",
    "s_hr": "ok",
    "m1": "tainted",
    "m2": "preserved",
    "m3": "tainted",
    "m4": "ok",
    "m5": "ok",
    "m6": "tainted",
    "a_commit": "tainted",
    "a_push": "tainted",
}


def test_scenario_revoke_mix(fresh_graph):
    db, tenant, gname = fresh_graph
    _build(db, tenant, gname)

    res = revoke(db, gname, tenant, root_id="s_web", reason="malicious page")
    assert res["idempotent"] is False
    statuses = get_node_statuses(db, gname, list(EXPECTED_AFTER_REVOKE))
    assert statuses == EXPECTED_AFTER_REVOKE
    assert res["counts"]["tainted"] == 5
    assert res["counts"]["preserved"] == 1
    affected = sorted(a["id"] for a in res["actions"])
    assert affected == ["a_commit", "a_push"]
    assert [a["id"] for a in res["irreversible"]] == ["a_push"]
    assert "abc123" in res["artifacts"]
    assert check_invariants(db, gname, expected_tenant=tenant) == []


def test_revoke_is_idempotent(fresh_graph):
    db, tenant, gname = fresh_graph
    _build(db, tenant, gname)
    first = revoke(db, gname, tenant, root_id="s_web", reason="bad")
    second = revoke(db, gname, tenant, root_id="s_web", reason="bad again")
    assert second["idempotent"] is True
    assert second["revocation_id"] == first["revocation_id"]
    assert second["state"] == "done"


def test_blame_chain_via_taint_parent(fresh_graph):
    db, tenant, gname = fresh_graph
    _build(db, tenant, gname)
    revoke(db, gname, tenant, root_id="s_web", reason="bad")
    chain, cur = [], "a_push"
    while cur:
        chain.append(cur)
        res = db.ro_query(gname, "MATCH (n:Node {id:$i}) RETURN n.taint_parent", {"i": cur}, op="test.blame")
        cur = res.result_set[0][0] if res.result_set else None
    assert chain == ["a_push", "m6", "m3", "m1", "s_web"]


def test_dry_run_writes_nothing(fresh_graph):
    db, tenant, gname = fresh_graph
    _build(db, tenant, gname)
    dry = revoke(db, gname, tenant, root_id="s_web", reason="preview", dry_run=True)
    assert dry["dry_run"] is True
    assert dry["counts"]["would_taint"] == 5
    assert dry["counts"]["would_preserve"] == 1
    statuses = get_node_statuses(db, gname, ["s_web", "m1", "m2", "a_push"])
    assert statuses == {"s_web": "ok", "m1": "ok", "m2": "ok", "a_push": "ok"}
    # no Revocation row was created
    res = db.ro_query(gname, Q_REVOCATION_LATEST, {"id": "s_web"}, op="test.check")
    assert not res.result_set


def test_race_child_created_mid_revoke_is_tainted(fresh_graph):
    db, tenant, gname = fresh_graph
    record_source(db, gname, tenant, kind="web", id="s_bad")
    remember(db, gname, tenant, text="r1", id="r1", derived_from=["s_bad"])

    def concurrent_ingest():
        # the child appears after discovery but before quarantine, while r1 still reads 'ok'
        remember(db, gname, tenant, text="late", id="r_late", derived_from=["r1"])

    revoke(db, gname, tenant, root_id="s_bad", reason="race", hook=concurrent_ingest)
    statuses = get_node_statuses(db, gname, ["r1", "r_late"])
    assert statuses == {"r1": "tainted", "r_late": "tainted"}
    assert check_invariants(db, gname) == []


def test_child_of_tainted_parent_is_born_quarantined(fresh_graph):
    db, tenant, gname = fresh_graph
    record_source(db, gname, tenant, kind="web", id="s_bad")
    remember(db, gname, tenant, text="r1", id="r1", derived_from=["s_bad"])
    revoke(db, gname, tenant, root_id="s_bad", reason="bad")
    born = remember(db, gname, tenant, text="after", id="r_after", derived_from=["r1"])
    assert born.status == "quarantined"
    assert "low_integrity" in born.warnings


def test_reinstate_restores_everything(fresh_graph):
    db, tenant, gname = fresh_graph
    _build(db, tenant, gname)
    revoke(db, gname, tenant, root_id="s_web", reason="bad")
    out = reinstate(db, gname, tenant, root_id="s_web")
    assert out["dry_run"] is False
    assert out["remaining_roots"] == 0
    statuses = get_node_statuses(db, gname, list(EXPECTED_AFTER_REVOKE))
    assert set(statuses.values()) == {"ok"}
    assert check_invariants(db, gname) == []


def test_resume_incomplete_finishes_a_crashed_revocation(fresh_graph):
    db, tenant, gname = fresh_graph
    _build(db, tenant, gname)
    db.query(
        gname,
        "MATCH (r:Node {id:'s_web'}) SET r.status='revoked', r.revoked_at=1 "
        "WITH r CREATE (:Node:Revocation {id:'rev_crash', tenant:$t, root_id:'s_web', reason:'simulated crash', "
        "kind:'revoke', state:'running', started_at:1})",
        {"t": tenant},
        op="test.crash",
    )
    results = resume_incomplete(db, gname)
    assert len(results) == 1
    statuses = get_node_statuses(db, gname, list(EXPECTED_AFTER_REVOKE))
    assert statuses == EXPECTED_AFTER_REVOKE
    assert results[0]["state"] == "done"
    assert check_invariants(db, gname, expected_tenant=tenant) == []


def test_artifact_key_cross_session_link(fresh_graph):
    db, tenant, gname = fresh_graph
    record_action(db, gname, tenant, tool="write", summary="wrote README", id="a_write",
                  artifact_key="README.md@aabbccdd", artifacts=["README.md"])
    remember(db, gname, tenant, text="rule", id="m_rule", artifact="CLAUDE.md",
             artifact_key="CLAUDE.md@11223344")
    assert artifact_lookup(db, gname, "README.md@aabbccdd") == ("Action", "a_write")
    assert artifact_lookup(db, gname, "CLAUDE.md@11223344") == ("Memory", "m_rule")
    assert artifact_lookup(db, gname, "missing@0000") is None


def test_report_counts(fresh_graph):
    db, tenant, gname = fresh_graph
    _build(db, tenant, gname)
    revoke(db, gname, tenant, root_id="s_web", reason="bad")
    rep = report(db, gname)
    assert rep["by_status"]["revoked"] == 1
    assert rep["by_status"]["tainted"] == 5
    assert rep["by_status"]["preserved"] == 1
    assert rep["revocations"]["done"] == 1


def test_ingest_and_revoke_errors(fresh_graph):
    db, tenant, gname = fresh_graph
    record_source(db, gname, tenant, kind="web", id="s1")
    with pytest.raises(NotFoundInGraph):
        remember(db, gname, tenant, text="x", id="m1", derived_from=["ghost"])
    with pytest.raises(NotFoundInGraph):
        remember(db, gname, tenant, text="x", id="m2", corroborated_by=["ghost"])
    with pytest.raises(InvalidArgument):
        remember(db, gname, tenant, text="x", id="m3", mkind="nonsense")
    with pytest.raises(TooLarge):
        remember(db, gname, tenant, text="x" * 2001, id="m4")
    with pytest.raises(NotFoundInGraph):
        revoke(db, gname, tenant, root_id="ghost", reason="x")
    record_action(db, gname, tenant, tool="bash", id="a1")
    with pytest.raises(InvalidArgument):
        revoke(db, gname, tenant, root_id="a1", reason="x")
    with pytest.raises(InvalidArgument):
        revoke(db, gname, tenant, root_id="s1", reason="x", kind="bogus")
    with pytest.raises(Conflict):
        record_source(db, gname, tenant, kind="web", id="s1")


def test_corroborate_requires_existing_nodes(fresh_graph):
    db, tenant, gname = fresh_graph
    record_source(db, gname, tenant, kind="file", id="s1")
    remember(db, gname, tenant, text="m", id="m1")
    corroborate(db, gname, "m1", "s1", by="human")
    with pytest.raises(NotFoundInGraph):
        corroborate(db, gname, "m1", "ghost")
    with pytest.raises(NotFoundInGraph):
        corroborate(db, gname, "ghost", "s1")
    with pytest.raises(InvalidArgument):
        corroborate(db, gname, "m1", "s1", by="nobody")
