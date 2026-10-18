"""F-12 - confidentiality labels and scenario S6: a private tag reaching a public audience is
blocked by the gate with the path, and a superset audience passes."""
from __future__ import annotations

import pytest

from pedigree.engine.gate import check_action
from pedigree.engine.ingest import get_node_statuses, record_source, remember


def test_confidentiality_blocks_a_public_destination(fresh_graph):
    db, tenant, gname = fresh_graph
    summary = "demo_s6_summary"
    record_source(db, gname, tenant, id="demo_s6_hr", kind="file", uri="file:///hr/notes.txt", conf=["hr"])
    remember(db, gname, tenant, id=summary, text="HR notes summary", derived_from=["demo_s6_hr"])

    # the label inherited from the source at write time
    statuses = get_node_statuses(db, gname, [summary])
    assert statuses[summary] == "ok"
    conf_eff = db.ro_query(gname, "MATCH (n {id:$i}) RETURN n.conf_eff", {"i": summary}).result_set[0][0]
    assert conf_eff == ["hr"]

    blocked = check_action(db, gname, {"tool": "Write", "summary": "into README.md",
                                       "audience": ["public"], "effect": "reversible",
                                       "risk": "low"}, relied_on=[summary])
    assert blocked["decision"] == "block"
    reasons = [reason["code"] for reason in blocked["reasons"]]
    assert "confidentiality_violation" in reasons
    assert blocked["hook"]["hookSpecificOutput"]["permissionDecision"] == "deny"

    allowed = check_action(db, gname, {"tool": "Write", "summary": "into HR_NOTES.md",
                                       "audience": ["public", "hr"], "effect": "reversible",
                                       "risk": "low"}, relied_on=[summary])
    assert allowed["decision"] == "allow"

    # a local destination defaults to audience ['local'], which does not include the tag either
    # (the caller declares the clearance)
    local = check_action(db, gname, {"tool": "Write", "summary": "keep local",
                                     "effect": "reversible", "risk": "low"}, relied_on=[summary])
    assert local["decision"] == "block"
    assert any(reason["code"] == "confidentiality_violation" for reason in local["reasons"])
    with_tag = check_action(db, gname, {"tool": "Write", "summary": "into HR_NOTES.md",
                                        "audience": ["hr"], "effect": "reversible",
                                        "risk": "low"}, relied_on=[summary])
    assert with_tag["decision"] == "allow"


def test_confidentiality_is_inherited_by_dependents(fresh_graph):
    db, tenant, gname = fresh_graph

    record_source(db, gname, tenant, id="src_hr", kind="file", uri="hr/x.csv", conf=["hr"])
    remember(db, gname, tenant, id="m1", text="a", derived_from=["src_hr"])
    remember(db, gname, tenant, id="m2", text="b", derived_from=["m1"])
    gate = check_action(db, gname, {"tool": "WebFetch", "summary": "post it",
                                    "audience": ["public"], "effect": "reversible",
                                    "risk": "low"}, relied_on=["m2"])
    assert gate["decision"] == "block"
    assert any(reason["code"] == "confidentiality_violation" for reason in gate["reasons"])


@pytest.mark.parametrize("audience,decision", [
    (["public"], "block"),
    (["public", "hr"], "block"),            # a partial superset is still missing `legal`
    (["public", "hr", "legal"], "allow"),   # the full superset is the boundary
])
def test_audience_superset_is_the_boundary(fresh_graph, audience, decision):
    db, tenant, gname = fresh_graph
    record_source(db, gname, tenant, id="src_hr2", kind="file", uri="hr/y.csv", conf=["hr", "legal"])
    remember(db, gname, tenant, id="m", text="c", derived_from=["src_hr2"])
    gate = check_action(db, gname, {"tool": "Write", "summary": "x", "audience": audience,
                                    "effect": "reversible", "risk": "low"}, relied_on=["m"])
    assert gate["decision"] == decision
