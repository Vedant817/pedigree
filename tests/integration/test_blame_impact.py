"""AT0.2-ish / F-04: blame and impact against a real FalkorDB (independent of the
existing test_core_scenario, which borrows its shape from the verified prototype)."""

from __future__ import annotations

import pytest

from pedigree.engine.blame import blame, impact
from pedigree.engine.ingest import get_node_statuses, record_action, record_source, remember
from pedigree.engine.revoke import report, revoke
from pedigree.errors import InvalidArgument, NotFoundInGraph


def _build(db, tenant, gname):
    record_source(db, gname, tenant, kind="web", id="s_web", uri="http://evil.example/x", title="page")
    record_source(db, gname, tenant, kind="file", id="s_doc", uri="docs/README.md")
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


def test_blame_returns_the_taint_chain_to_the_revoked_root(fresh_graph):
    db, tenant, gname = fresh_graph
    _build(db, tenant, gname)
    revoke(db, gname, tenant, root_id="s_web", reason="bad")

    result = blame(db, gname, "a_push")
    chains = []
    for root in result["roots"]:
        if root["id"] == "s_web":
            chains.append(root["path"])
    assert any(ch == ["a_push", "m6", "m3", "m1", "s_web"] for ch in chains), result


def test_blame_rejects_unknown_id(fresh_graph):
    db, tenant, gname = fresh_graph
    _build(db, tenant, gname)
    with pytest.raises(NotFoundInGraph):
        blame(db, gname, "ghost")


def test_blame_validates_max_depth(fresh_graph):
    db, tenant, gname = fresh_graph
    _build(db, tenant, gname)
    with pytest.raises(InvalidArgument):
        blame(db, gname, "m1", max_depth=0)
    with pytest.raises(InvalidArgument):
        blame(db, gname, "m1", max_depth=True)


def test_impact_groups_descendants_and_flags_irreversible(fresh_graph):
    db, tenant, gname = fresh_graph
    _build(db, tenant, gname)
    revoke(db, gname, tenant, root_id="s_web", reason="bad")

    res = impact(db, gname, "s_web")
    assert res["counts"]["n_total"] == 7
    assert res["counts"]["by_status"].get("tainted") == 5
    assert res["counts"]["by_status"].get("preserved") == 1
    assert res["counts"]["by_status"].get("ok") == 1
    # labels: 5 affected Memory nodes (m1..m4, m6) + 2 Action nodes
    assert res["counts"]["by_label"].get("Memory") == 5
    assert res["counts"]["by_label"].get("Action") == 2
    ids = {a["id"] for a in res["irreversible"]}
    assert ids == {"a_push"}
    assert any("abc123" in a.get("artifacts", []) for a in res["actions"]
               if a["id"] == "a_push") or any("abc123" in a["artifacts"] for a in res["actions"])
    # artifacts reported from the affected actions
    action_arts = {art for a in res["actions"] for art in a["artifacts"]}
    assert "abc123" in action_arts


def test_impact_rejects_unknown_id(fresh_graph):
    db, tenant, gname = fresh_graph
    _build(db, tenant, gname)
    with pytest.raises(NotFoundInGraph):
        impact(db, gname, "ghost")


def test_blame_and_impact_are_read_only(fresh_graph):
    db, tenant, gname = fresh_graph
    _build(db, tenant, gname)
    revoke(db, gname, tenant, root_id="s_web", reason="bad")

    before = get_node_statuses(db, gname, ["m1", "m2", "m3", "m4", "m5", "m6", "a_push"])
    before_rev = report(db, gname)["revocations"].get("done")

    blame(db, gname, "a_push")
    impact(db, gname, "s_web")
    blame(db, gname, "m2")
    impact(db, gname, "m3")

    after = get_node_statuses(db, gname, ["m1", "m2", "m3", "m4", "m5", "m6", "a_push"])
    after_rev = report(db, gname)["revocations"].get("done")
    assert before == after, f"statuses mutated by read-only calls: {before} -> {after}"
    assert before_rev == after_rev


def test_impact_of_a_leaf_is_empty(fresh_graph):
    db, tenant, gname = fresh_graph
    _build(db, tenant, gname)
    res = impact(db, gname, "m4")
    assert res["counts"]["n_total"] == 0
    assert res["irreversible"] == []
