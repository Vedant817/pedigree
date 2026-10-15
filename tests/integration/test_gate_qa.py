"""Independent F-11 acceptance probes, using real isolated FalkorDB graphs."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import httpx
import uvicorn

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings
from pedigree.engine.gate import check_action
from pedigree.engine.ingest import ensure_session, read_window, record_source, remember, session_read
from pedigree.engine.revoke import revoke
from pedigree.mcp_server import build_mcp


def test_qa_all_fired_rules_and_precedence(fresh_graph):
    db, tenant, graph = fresh_graph
    record_source(db, graph, tenant, id="bad", kind="web", conf=["team"])
    revoke(db, graph, tenant, root_id="bad")
    result = check_action(db, graph, {"tool": "Edit", "risk": "high"}, relied_on=["bad"])
    assert result["decision"] == "block"
    assert [r["code"] for r in result["reasons"]] == [
        "tainted_ancestor", "confidentiality_violation", "untrusted_influence"]
    assert result["would_verify"] == ["bad"]


def test_qa_decision_never_calls_write_client(fresh_graph, monkeypatch):
    db, tenant, graph = fresh_graph
    record_source(db, graph, tenant, id="src", kind="file")

    def forbidden(*args, **kwargs):
        raise AssertionError("decision path called db.query")

    monkeypatch.setattr(db, "query", forbidden)
    assert check_action(db, graph, {"tool": "Read"}, relied_on=["src"])["decision"] == "allow"
    monkeypatch.undo()


def test_qa_duplicate_anchors_are_checked_once(fresh_graph):
    db, tenant, graph = fresh_graph
    record_source(db, graph, tenant, id="src", kind="file")
    result = check_action(db, graph, {"tool": "Read"}, relied_on=["src"] * 64)
    assert result["checked"] == 1
    assert result["decision"] == "allow"


def test_qa_read_window_record_captures_actual_distinct_anchors(fresh_graph):
    db, tenant, graph = fresh_graph
    ensure_session(db, graph, tenant, "sess")
    for i in range(3):
        record_source(db, graph, tenant, id=f"src{i}", kind="file")
        session_read(db, graph, "sess", f"src{i}", now=i + 1)
    session_read(db, graph, "sess", "src0", now=10)
    assert read_window(db, graph, "sess", k=2) == ["src0", "src2"]
    result = check_action(db, graph, {"tool": "Read"}, session_id="sess", record=True, tenant=tenant)
    assert result["checked"] == 3
    rows = db.ro_query(graph, "MATCH (a:Action {id:$id})-[:DERIVED_FROM]->(p) RETURN p.id",
                       {"id": result["action_id"]}).result_set
    assert {r[0] for r in rows} == {"src0", "src1", "src2"}


def test_qa_missing_taint_parent_is_documented(fresh_graph):
    db, tenant, graph = fresh_graph
    record_source(db, graph, tenant, id="src", kind="file")
    remember(db, graph, tenant, id="mem", derived_from=["src"])
    db.query(graph, "MATCH (n {id:'mem'}) SET n.status='tainted'")
    result = check_action(db, graph, {"tool": "Edit", "risk": "medium"}, relied_on=["mem"])
    assert result["decision"] == "block"
    assert result["reasons"][0]["path"] == ["mem"]
    assert "taint_parent missing" in result["reasons"][0]["detail"]


def test_qa_policy_audience_is_applied(fresh_graph, tmp_path):
    db, tenant, graph = fresh_graph
    record_source(db, graph, tenant, id="secret", kind="file", conf=["team"])
    policy = tmp_path / "policy.yaml"
    policy.write_text("rules:\n  - tool: '^Deploy$'\n    effect: reversible\n    risk: low\n    audience: [team]\n", encoding="utf-8")
    result = check_action(db, graph, {"tool": "Deploy"}, relied_on=["secret"], policy_path=policy)
    assert result["decision"] == "allow"


def test_qa_record_missing_anchor_returns_reverify_without_partial_write(fresh_graph):
    db, tenant, graph = fresh_graph
    result = check_action(db, graph, {"tool": "Read"}, relied_on=["ghost"], record=True, tenant=tenant)
    assert result["decision"] == "reverify"
    assert result["recording_error"] == {"code": "not_in_graph", "missing": ["ghost"]}
    assert "action_id" not in result
    assert db.ro_query(graph, "MATCH (a:Action) RETURN count(a)").result_set == [[0]]


def test_qa_live_socket_http_and_mcp_same_revoked_anchor(fresh_graph):
    db, tenant, graph = fresh_graph
    settings = Settings(pedigree_admin_token="dummy-admin")
    registry = TenantRegistry(db, settings)
    credential = registry.create_tenant(tenant)
    record_source(db, graph, tenant, id="root", kind="rules_file")
    ensure_session(db, graph, tenant, "hooksess")
    session_read(db, graph, "hooksess", "root")
    revoke(db, graph, tenant, root_id="root")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(db, settings), log_level="error"))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
            response = client.post("/v1/gate", headers={"Authorization": "Bearer " + credential.token},
                                   json={"action": {"tool": "Bash", "summary": "git push"},
                                         "relied_on": ["root"]})
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["decision"] == "block"
            assert result["hook"]["hookSpecificOutput"]["permissionDecision"] == "deny"
            print(f"LIVE HTTP POST /v1/gate: {response.status_code}; decision=block; hook=deny; path={result['reasons'][0]['path']}")

        async def run():
            mcp = build_mcp(db, settings).server
            response = await mcp.call_tool("pedigree_check_action", {
                "token": credential.token, "tool": "Bash", "summary": "git push", "relied_on": ["root"]})
            result = json.loads(response.content[0].text)
            assert result["ok"] is True
            assert result["result"]["decision"] == "block"
            print("MCP pedigree_check_action: ok=true; decision=block; hook=deny")
        asyncio.run(run())
        env = {**os.environ, "PEDIGREE_URL": f"http://127.0.0.1:{port}",
               "PEDIGREE_TOKEN": credential.token}
        hook_path = Path(__file__).resolve().parents[2] / "adapters" / "claude" / "pedigree_hook.py"
        process = subprocess.run([sys.executable, "-I", "-S", str(hook_path), "pre"],
                                 input=json.dumps({"session_id": "hooksess", "tool_name": "Bash",
                                                   "tool_input": {"command": "git push"}}),
                                 text=True, capture_output=True, env=env, timeout=15, check=True)
        assert process.stderr == ""
        assert json.loads(process.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
        print("CLAUDE subprocess -I -S pre -> live HTTP -> FalkorDB: exit=0; stderr=empty; hook=deny")
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        listener.close()
        registry.db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": tenant})
    assert not worker.is_alive()
