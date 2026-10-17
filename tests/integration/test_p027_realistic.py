"""The realistic demo seed stores the poisoned README under the force-push."""
from pedigree.db import queries as Q
from pedigree.demo_realistic import INSTALL_ID, POISON_ID, PUSH_ID, seed_realistic
from pedigree.engine.ingest import get_node_statuses
from pedigree.engine.revoke import revoke


def test_seed_then_revoke_taints_the_force_push(fresh_graph):
    db, tenant, graph = fresh_graph
    result = seed_realistic(db, tenant)
    assert result["nodes"] >= 300
    assert result["actions"] >= 40
    assert result["created"] == result["nodes"]
    parents = {
        parent
        for _child, parent in db.ro_query(
            graph, Q.Q_PARENTS_OF, {"ids": [PUSH_ID, INSTALL_ID]}, op="demo.parents"
        ).result_set or []
    }
    assert parents == {INSTALL_ID, POISON_ID}
    again = seed_realistic(db, tenant)
    assert again["created"] == 0
    assert again["existing"] == result["nodes"]
    revoke(db, graph, tenant, root_id=POISON_ID, reason="poisoned installer readme")
    assert get_node_statuses(db, graph, [PUSH_ID])[PUSH_ID] == "tainted"
