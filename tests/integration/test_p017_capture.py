"""P-017: a bash read is parented on the file it read, not on earlier session reads."""
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings
from pedigree.engine.revoke import revoke


def test_bash_read_does_not_inherit_an_earlier_session_source(fresh_graph, tmp_path):
    db, tenant, graph = fresh_graph
    settings = Settings()
    registry = TenantRegistry(db, settings)
    token = registry.create_tenant(tenant).token
    client = TestClient(create_app(db, settings))
    headers = {"Authorization": "Bearer " + token}
    try:
        _run(db, tenant, graph, client, headers, tmp_path)
    finally:
        db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": tenant})


def _run(db, tenant, graph, client, headers, tmp_path):
    import importlib.util
    from pathlib import Path

    file = tmp_path / "notes.py"
    file.write_bytes(b"notes")
    spec = importlib.util.spec_from_file_location(
        "claude_hook_p017", Path(__file__).resolve().parents[2] / "adapters/claude/pedigree_hook.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)

    seeded = client.post("/v1/events", headers=headers, json={
        "runtime": "claude-code", "session_id": "sess_p017", "events": [
            {"type": "session"},
            {"type": "source_read", "source_kind": "web", "uri": "https://example.com/other",
             "content_hash": "ab" * 32, "id": "src_other_p017"},
            {"type": "session_read", "node_id": "src_other_p017"},
        ],
    })
    assert seeded.status_code == 200, seeded.text

    def send(path, payload=None):
        if payload is None:
            response = client.get(path, headers=headers)
        else:
            response = client.post(path, headers=headers, json=payload)
        assert response.status_code == 200, response.text
        return response.json()

    command = "cat " + file.resolve().as_posix()
    hook.handle("post", {"session_id": "sess_p017", "tool_name": "Bash", "cwd": str(tmp_path),
                         "tool_input": {"command": command}}, send)
    rows = db.ro_query(graph, """
        MATCH (a:Action)-[d:DERIVED_FROM]->(p)
        WHERE a.tool = 'Bash'
        RETURN p.uri, a.status, d.via
    """).result_set
    assert rows == [[file.resolve().as_posix(), "ok", "hook"]], rows
    revoke(db, graph, tenant, root_id="src_other_p017")
    status = db.ro_query(graph, "MATCH (a:Action {tool:'Bash'}) RETURN a.status").result_set
    assert status == [["ok"]], status
    file_id = db.ro_query(
        graph, "MATCH (s:Source {uri:$uri}) RETURN s.id", {"uri": file.resolve().as_posix()}
    ).result_set[0][0]
    revoke(db, graph, tenant, root_id=file_id)
    tainted = db.ro_query(graph, "MATCH (a:Action {tool:'Bash'}) RETURN a.status").result_set
    assert tainted == [["tainted"]], tainted
