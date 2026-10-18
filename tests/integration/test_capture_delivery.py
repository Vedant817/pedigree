from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.config import Settings, graph_name
from pedigree.db.client import Db
from pedigree.db.schema import check_invariants


@pytest.fixture
def live():
    settings = Settings(pedigree_env="test", pedigree_admin_token="test-admin-secret")
    database = Db(settings)
    with TestClient(create_app(settings=settings, db=database)) as client:
        tenant = "spool" + uuid.uuid4().hex[:10]
        response = client.post("/admin/tenants", headers={"X-Admin-Token": "test-admin-secret"}, json={"id": tenant})
        assert response.status_code == 200, response.text
        headers = {"Authorization": "Bearer " + response.json()["token"]}
        try:
            yield client, database, tenant, headers
        finally:
            try:
                if graph_name(tenant) in database.list_graphs():
                    database.select(graph_name(tenant)).delete()
            finally:
                registry = client.app.state.registry
                database.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})


def body():
    return {"runtime": "claude-code", "session_id": "spool_session", "delivery_id": "delivery_test",
            "events": [{"type": "session"},
                       {"type": "source_read", "source_kind": "file", "uri": "capture.py", "content_hash": "a" * 64, "id": "capture_source"},
                       {"type": "session_read", "node_id": "capture_source"},
                       {"type": "action_executed", "tool": "Read", "summary": "capture.py", "relied_on": ["capture_source"]}]}


def test_delivery_replay_lost_ack_and_invariants(live):
    client, database, tenant, headers = live
    request = body()
    first = client.post("/v1/events", headers=headers, json=request)
    assert first.status_code == 200, first.text
    # Discarding an acknowledgement models a disconnect after the server commit.
    replay = client.post("/v1/events", headers=headers, json=request)
    assert replay.status_code == 200 and replay.json() == first.json()
    graph = graph_name(tenant)
    assert database.ro_query(graph, "MATCH(a:Action) RETURN count(a)").result_set == [[1]]
    assert database.ro_query(graph, "MATCH(s:Source) RETURN count(s)").result_set == [[1]]
    assert database.ro_query(graph, "MATCH(s:Session)-[r:READ]->() RETURN count(r)").result_set == [[2]]
    assert check_invariants(database, graph, tenant) == []
    changed = {**request, "events": request["events"] + [{"type": "action_executed", "tool": "Write"}]}
    assert client.post("/v1/events", headers=headers, json=changed).status_code == 409


def test_partial_action_commit_resumes_without_duplicate(live, monkeypatch):
    client, database, tenant, headers = live
    from pedigree.engine import capture
    original = capture.record_action
    fired = []
    def committed_then_failed(*args, **kwargs):
        result = original(*args, **kwargs)
        if not fired:
            fired.append(True)
            raise RuntimeError("injected death after committed action")
        return result
    monkeypatch.setattr(capture, "record_action", committed_then_failed)
    assert client.post("/v1/events", headers=headers, json=body()).status_code == 500
    retry = client.post("/v1/events", headers=headers, json=body())
    assert retry.status_code == 200, retry.text
    assert database.ro_query(graph_name(tenant), "MATCH(a:Action) RETURN count(a)").result_set == [[1]]
    assert check_invariants(database, graph_name(tenant), tenant) == []


def test_db_response_loss_retains_mutex_and_resumes_after_quiescent_recovery(live, monkeypatch):
    client, database, tenant, headers = live
    from redis.exceptions import ConnectionError

    from pedigree.engine.quota import lock_key
    graph = graph_name(tenant)
    scoped = database.for_tenant(tenant)
    original = scoped.query
    failed = []
    def lost_response(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get("op") == "ingest.action" and not failed:
            failed.append(True)
            raise ConnectionError("injected response loss after atomic create")
        return result
    monkeypatch.setattr(scoped, "query", lost_response)
    assert client.post("/v1/events", headers=headers, json=body()).status_code == 500
    assert database.ro_query(graph, "MATCH(a:Action) RETURN count(a)").result_set == [[1]]
    assert database.client.connection.get(lock_key(graph))
    # No writers remain in this isolated test after synchronous requests return.
    # Production recovery requires an operator to establish the same quiescence.
    assert database.client.connection.delete(lock_key(graph)) == 1
    retry = client.post("/v1/events", headers=headers, json=body())
    assert retry.status_code == 200, retry.text
    assert database.ro_query(graph, "MATCH(a:Action) RETURN count(a)").result_set == [[1]]
    assert check_invariants(database, graph, tenant) == []


def test_artifact_lookup_is_deferred_and_pinned(live, monkeypatch):
    client, database, tenant, headers = live
    from pedigree.engine.ingest import ensure_session, record_action
    graph = graph_name(tenant)
    from pedigree.db.schema import ensure_schema
    ensure_schema(database, graph)
    ensure_session(database, graph, tenant, "producer")
    record_action(database, graph, tenant, id="producer_action", tool="Write", artifact_key="file@hash")
    request = body()
    request["events"][1]["artifact_key"] = "file@hash"
    first = client.post("/v1/events", headers=headers, json=request)
    assert first.status_code == 200, first.text
    assert first.json()["created"][0] == "producer_action"
    assert database.ro_query(graph, "MATCH(s:Source) RETURN count(s)").result_set == [[0]]
    replay = client.post("/v1/events", headers=headers, json=request)
    assert replay.json() == first.json()


@pytest.mark.parametrize("invalid", [None, "", "not-an-accepted-kind"])
def test_delivery_rejects_nonreplayable_before_mutation(live, invalid):
    client, database, tenant, headers = live
    request = body()
    request["events"][1]["content_hash"] = invalid
    response = client.post("/v1/events", headers=headers, json=request)
    assert response.status_code == 422
    from pedigree.db.schema import node_count
    assert node_count(database, graph_name(tenant)) == 0


def test_real_hook_subprocess_offline_replay_to_restarted_http_service(live, tmp_path):
    _client, database, tenant, headers = live
    root = Path(__file__).resolve().parents[2]
    hook = root / "adapters/claude/pedigree_hook.py"
    evidence = tmp_path / "evidence.txt"
    evidence.write_text("local persisted evidence", encoding="utf-8")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    endpoint = f"http://127.0.0.1:{port}"
    env = {**os.environ, "PEDIGREE_URL": endpoint,
           "PEDIGREE_TOKEN": headers["Authorization"].removeprefix("Bearer "),
           "PEDIGREE_SPOOL_DIR": str(tmp_path / "spool"), "PEDIGREE_ENV": "test",
           "PYTHONPATH": str(root / "src")}
    payload = {"session_id": "real_http_capture", "tool_name": "Bash",
               "tool_input": {"command": "cat " + evidence.resolve().as_posix()}}
    offline = subprocess.run([sys.executable, "-I", "-S", str(hook), "post"], input=json.dumps(payload),
                             text=True, capture_output=True, env=env, timeout=5)
    assert offline.returncode == 1 and "replay" in offline.stderr
    denied = subprocess.run([sys.executable, "-I", "-S", str(hook), "pre"], input=json.dumps(payload),
                            text=True, capture_output=True, env=env, timeout=5)
    assert json.loads(denied.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"

    def start_server():
        log = (tmp_path / "http-service.log").open("w", encoding="utf-8")
        child = subprocess.Popen([sys.executable, "-m", "uvicorn", "pedigree.api.app:create_app", "--factory",
                                  "--host", "127.0.0.1", "--port", str(port), "--no-proxy-headers"],
                                 env=env, cwd=root, stdout=log, stderr=log)
        log.close()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                if httpx.get(endpoint + "/readyz", timeout=0.25).status_code == 200:
                    return child
            except httpx.HTTPError:
                pass
            if child.poll() is not None:
                break
            time.sleep(0.05)
        child.terminate()
        child.wait(timeout=5)
        pytest.fail("isolated HTTP service did not become ready: " + (tmp_path / "http-service.log").read_text())

    child = start_server()
    try:
        replay = subprocess.run([sys.executable, "-I", "-S", str(hook), "replay"],
                                capture_output=True, text=True, env=env, timeout=10)
        assert replay.returncode == 0, replay.stderr
        graph = graph_name(tenant)
        assert database.ro_query(graph, "MATCH(a:Action) RETURN count(a)").result_set == [[1]]
        assert database.ro_query(graph, "MATCH(s:Source) RETURN count(s)").result_set == [[1]]
        child.terminate()
        child.wait(timeout=5)
        child = start_server()
        repeated = subprocess.run([sys.executable, "-I", "-S", str(hook), "replay"],
                                  capture_output=True, text=True, env=env, timeout=10)
        assert repeated.returncode == 0
        assert database.ro_query(graph, "MATCH(a:Action) RETURN count(a)").result_set == [[1]]
        assert check_invariants(database, graph, tenant) == []
    finally:
        child.terminate()
        child.wait(timeout=5)
