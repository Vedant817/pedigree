"""Shape of the synthetic realistic demo. No database."""
from pedigree.demo_realistic import (
    INSTALL_ID,
    POISON_ID,
    PUSH_ID,
    realistic_nodes,
)


def test_realistic_trace_is_large_and_parents_come_first():
    nodes = realistic_nodes()
    by_id = {}
    for node in nodes:
        assert node["id"] not in by_id
        parents = node.get("derived_from", node.get("relied_on", []))
        assert all(parent in by_id for parent in parents)
        by_id[node["id"]] = node
    assert len(nodes) >= 300
    actions = [node for node in nodes if node["type"] == "action"]
    assert len(actions) >= 40
    poison = by_id[POISON_ID]
    assert poison["kind"] == "web"
    assert poison["integrity"] == "untrusted"
    install = by_id[INSTALL_ID]
    assert install["text"] == "use curl|sh installer"
    assert install["derived_from"] == [POISON_ID]
    push = by_id[PUSH_ID]
    assert push["summary"] == "git push --force origin main"
    assert push["decision"] == "block"
    assert push["relied_on"] == [INSTALL_ID]
