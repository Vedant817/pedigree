"""Independent round-two regressions: disposable DB and owned API8119 only."""
import hashlib
import os
import socket
import subprocess
import threading
from pathlib import Path

import pytest
import uvicorn

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.engine.components import weak_components


@pytest.mark.parametrize("label", ["Session", "Agent", "Revocation"])
@pytest.mark.parametrize("relation", ["DERIVED_FROM", "CORROBORATED_BY"])
def test_metadata_bridges_excluded_before_wcc(fresh_graph, label, relation):
    db, _, graph = fresh_graph
    # Closed constants above, never user-provided labels/relationship types.
    db.query(graph, "CREATE(a:Node:Source {id:'a'}),(b:Node:Action {id:'b'}),"
             f"(m:Node:{label} {{id:'metadata'}}),"
             f"(a)-[:{relation}]->(m),(m)-[:{relation}]->(b)")
    result = weak_components(db, graph)
    assert sorted(c["nodes"] for c in result["components"]) == [1, 1]


def test_wcc_label_union_counts_multilabel_once(fresh_graph):
    db, _, graph = fresh_graph
    db.query(graph, "CREATE(s:Node:Source {id:'s'}),(m:Node:Memory {id:'m'}),"
             "(a:Node:Action {id:'a'}),(u:Node:Source:Memory:Action {id:'union'}),"
             "(x:Node:Session {id:'excluded'}),"
             "(s)-[:DERIVED_FROM]->(m),(m)-[:CORROBORATED_BY]->(a)")
    result = weak_components(db, graph)
    assert sorted(c["nodes"] for c in result["components"]) == [1, 3]
    assert result["truncated"] is False


def test_independent_native_attacks_real_http_db(fresh_graph):
    db, tenant, graph = fresh_graph
    registry = TenantRegistry(db)
    credential = registry.create_tenant(tenant)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 8119))
    listener.listen()
    server = uvicorn.Server(uvicorn.Config(create_app(db, db.settings), log_level="error"))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        script = Path(__file__).with_name("release_round2_native.mjs")
        result = subprocess.run(["node", "--test", str(script)], capture_output=True,
                                text=True, timeout=60, env={**os.environ,
                                "ROUND2_URL": "http://127.0.0.1:8119",
                                "ROUND2_TOKEN": credential.agent_token})
        print(result.stdout)
        assert result.returncode == 0, result.stdout + result.stderr
        rows = db.ro_query(graph, "MATCH(a:Action) RETURN a.tool,a.artifact_key").result_set
        assert len(rows) == 2 and {r[0] for r in rows} == {"edit", "bash"}, rows
        sources = db.ro_query(graph, "MATCH(s:Source {kind:'tool_output'}) "
                              "RETURN s.content_hash,s.integrity").result_set
        assert sources == [[hashlib.sha256(b"private-output-canary").hexdigest(), "untrusted"]]
        assert db.ro_query(graph, "MATCH(s:Source) RETURN s.text").result_set == [[None]]
        print("REAL DB: exactly edit/bash actions; output digest untrusted; no source text")
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        listener.close()
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})
        db.execute_admin("ACL", "DELUSER", "t_" + tenant)
