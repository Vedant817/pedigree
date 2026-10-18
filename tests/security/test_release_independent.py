"""Independent release attacks; use only uniquely owned synthetic tenants."""
import asyncio
import importlib.util
import json
import secrets
import threading
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import NoPermissionError, ResponseError

from pedigree.api.app import _startup_resume, create_app
from pedigree.config import Settings, graph_name
from pedigree.db.client import Db
from pedigree.db.schema import check_invariants, ensure_schema
from pedigree.engine.components import weak_components
from pedigree.engine.revoke import revoke, tenant_lock
from pedigree.mcp_server import build_mcp


@pytest.fixture
def release_service():
    settings = Settings(_env_file=None, pedigree_env="test", pedigree_db_acl=True,
                        pedigree_db_acl_secret=secrets.token_urlsafe(32))
    db = Db(settings)
    assert db.ping() and db.module_version() == 42201
    app = create_app(db, settings)
    registry = app.state.registry
    ids = ["ind" + uuid.uuid4().hex[:12] for _ in range(2)]
    credentials = [registry.create_tenant(t, node_cap=100) for t in ids]
    for tenant in ids:
        ensure_schema(db, graph_name(tenant))
    # No lifespan here: explicit startup-race test controls its own worker.
    client = TestClient(app)
    try:
        yield client, db, registry, credentials
    finally:
        client.close()
        for tenant in ids:
            base = graph_name(tenant)
            for name in db.list_graphs():
                if name == base or name.startswith(base + ":"):
                    db.select(name).delete()
            db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})
            db.execute_admin("ACL", "DELUSER", "t_" + tenant)


def headers(credential):
    return {"Authorization": "Bearer " + credential.agent_token}


def envelope(delivery="independent_delivery"):
    return {"runtime": "claude-code", "session_id": "ind_session", "delivery_id": delivery,
            "events": [{"type": "session"}, {"type": "source_read", "source_kind": "file",
                       "uri": "synthetic.py", "content_hash": "a" * 64, "id": "alias"}]}


def test_raw_acl_keys_scripts_copy_and_registry(release_service):
    _, db, registry, (a, b) = release_service
    own, foreign = graph_name(a.tenant_id), graph_name(b.tenant_id)
    raw = db.for_tenant(a.tenant_id).client.connection
    targets = [foreign, foreign + ":ck:backup", own + "x", registry.gname,
               "ped:registry", "pedigree:quota:mutex:" + foreign]
    db.client.connection.set("pedigree:quota:mutex:" + foreign, "sentinel")
    try:
        for target in targets:
            for command in [("GET", target), ("SET", target, "attack"), ("DEL", target),
                            ("EVAL", "return redis.call('GET',ARGV[1])", 0, target),
                            ("EVAL", "return redis.call('DEL',KEYS[1])", 1, target),
                            ("GRAPH.COPY", own, target + ":wi:1234abcd"),
                            ("GRAPH.RO_QUERY", target, "RETURN 1")]:
                with pytest.raises((NoPermissionError, ResponseError)) as denied:
                    raw.execute_command(*command)
                assert isinstance(denied.value, NoPermissionError) or "permission" in str(denied.value).lower(), str(denied.value)
        assert db.client.connection.get("pedigree:quota:mutex:" + foreign) == "sentinel"
        assert registry.get_record(b.tenant_id).status == "active"
    finally:
        db.client.connection.delete("pedigree:quota:mutex:" + foreign)


def test_bearer_overrides_claims_and_trusted_support_denied(release_service):
    client, db, _, (a, b) = release_service
    assert client.post("/v1/sources", headers=headers(b), json={"id": "foreign", "kind": "file", "uri": "foreign"}).status_code == 200
    spoof = {**headers(a), "X-Tenant-Id": b.tenant_id, "X-Admin-Token": "fake"}
    response = client.get("/v1/graph", headers=spoof, params={"tenant_id": b.tenant_id})
    assert response.status_code == 200 and "foreign" not in response.text
    for claim in [{"source_kind": "human"}, {"integrity": "trusted"}]:
        body = envelope()
        body["events"][1].update(claim)
        assert client.post("/v1/events", headers=headers(a), json=body).status_code == 403
    assert db.ro_query(graph_name(a.tenant_id), "MATCH(n) RETURN count(n)").result_set == [[0]]
    server = build_mcp(db, db.settings).server
    async def invoke():
        return await server.call_tool("pedigree_record_source", {
            "token": a.agent_token, "tenant_id": b.tenant_id, "kind": "human", "uri": "forged"})
    result = asyncio.run(invoke())
    assert json.loads(result.content[0].text)["ok"] is False
    # Also attack trust with the correct tenant, independently of claim mismatch.
    async def trusted():
        return await server.call_tool("pedigree_record_source", {
            "token": a.agent_token, "kind": "human", "uri": "forged"})
    assert json.loads(asyncio.run(trusted()).content[0].text)["error"]["code"] == "forbidden"
    assert db.ro_query(graph_name(b.tenant_id), "MATCH(n:Source) RETURN n.id").result_set == [["foreign"]]


def test_receipt_full_quota_replay_and_cross_tenant_same_id(release_service):
    client, db, registry, (a, b) = release_service
    db.query(registry.gname, "MATCH(t:Tenant {id:$id}) SET t.node_cap=3", {"id": a.tenant_id})
    body = envelope()
    first = client.post("/v1/events", headers=headers(a), json=body)
    assert first.status_code == 200, first.text
    # Full quota cannot prevent acknowledging an already committed envelope.
    assert client.post("/v1/events", headers=headers(a), json=body).json() == first.json()
    other = client.post("/v1/events", headers=headers(b), json=body)
    assert other.status_code == 200
    changed = envelope()
    changed["events"][1]["uri"] = "changed.py"
    assert client.post("/v1/events", headers=headers(a), json=changed).status_code == 409
    rejected = client.post("/v1/events", headers=headers(a), json=envelope("another_delivery"))
    assert rejected.json()["error"]["code"] == "quota_exceeded", rejected.text
    assert db.ro_query(graph_name(a.tenant_id), "MATCH(n) RETURN count(n)").result_set == [[3]]
    assert check_invariants(db, graph_name(a.tenant_id), a.tenant_id) == []


def test_agent_cannot_forge_trusted_corroboration(release_service):
    client, db, _, (a, b) = release_service
    assert client.post("/v1/sources", headers=headers(a), json={
        "id": "support", "kind": "file", "uri": "support.py"}).status_code == 200
    assert client.post("/v1/memories", headers=headers(a), json={
        "id": "belief", "text": "synthetic belief", "derived_from": ["support"]}).status_code == 200
    for by in ("human", "scanner"):
        assert client.post("/v1/corroborate", headers=headers(a), json={
            "memory_id": "belief", "source_id": "support", "by": by}).status_code == 403
    assert db.ro_query(graph_name(a.tenant_id), "MATCH()-[r:CORROBORATED_BY]->() RETURN count(r)").result_set == [[0]]
    assert client.post("/v1/corroborate", headers={"Authorization": "Bearer " + b.operator_token}, json={
        "memory_id": "belief", "source_id": "support", "by": "human"}).status_code == 404


def test_spool_credential_switch_and_wrong_ack_keep_original(monkeypatch, tmp_path):
    path = Path(__file__).resolve().parents[2] / "adapters/claude/pedigree_hook.py"
    spec = importlib.util.spec_from_file_location("independent_hook", path)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    monkeypatch.setenv("PEDIGREE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("PEDIGREE_TOKEN", "synthetic-agent-a")
    monkeypatch.setenv("PEDIGREE_SPOOL_DIR", str(tmp_path))
    spool = hook.Spool()
    spool.enqueue(envelope())
    with pytest.raises(ValueError, match="acknowledge"):
        spool.drain(lambda *args: {"delivery_id": "wrong"})
    assert spool.pending() == 1
    monkeypatch.setenv("PEDIGREE_TOKEN", "synthetic-agent-b")
    with pytest.raises(ValueError, match="changed"):
        spool.drain(lambda *args: pytest.fail("sent old evidence with new credential"))
    assert hook.Spool().pending() == 0 and spool.pending() == 1
    monkeypatch.setenv("PEDIGREE_TOKEN", "synthetic-agent-a")
    seen = []
    def lost_ack(_, body):
        seen.append(body)
        raise OSError("lost acknowledgement")
    with pytest.raises(OSError):
        spool.drain(lost_ack)
    spool.drain(lambda _, body: seen.append(body) or {"delivery_id": body["delivery_id"]})
    assert seen[0] == seen[1] and spool.pending() == 0


def test_startup_blocks_behind_real_mutation_and_preserves_revoked_source(release_service, monkeypatch):
    client, db, registry, (a, _) = release_service
    scoped = db.for_tenant(a.tenant_id)
    graph = graph_name(a.tenant_id)
    assert client.post("/v1/sources", headers=headers(a), json={"id": "root", "kind": "file", "uri": "root"}).status_code == 200
    selected = threading.Event()
    original = db.for_tenant
    def selecting(tenant):
        if tenant == a.tenant_id:
            selected.set()
        return original(tenant)
    monkeypatch.setattr(db, "for_tenant", selecting)
    worker = threading.Thread(target=_startup_resume, args=(db, registry))
    with tenant_lock(a.tenant_id):
        worker.start()
        assert selected.wait(3)
        revoke(scoped, graph, a.tenant_id, root_id="root", reason="independent startup race")
        assert worker.is_alive()
    worker.join(5)
    assert not worker.is_alive()
    assert scoped.ro_query(graph, "MATCH(n:Source {id:'root'}) RETURN n.status").result_set == [["revoked"]]
    assert check_invariants(scoped, graph, a.tenant_id) == []


def test_wcc_metadata_read_edges_and_foreign_graph_do_not_count(release_service):
    client, db, _, (a, b) = release_service
    assert client.post("/v1/events", headers=headers(a), json=envelope()).status_code == 200
    foreign = graph_name(b.tenant_id)
    db.query(foreign, "UNWIND range(1,8) AS i CREATE (:Node:Source {id:toString(i)})")
    result = client.get("/v1/audit/components", headers=headers(a)).json()
    assert [c["nodes"] for c in result["components"]] == [1]
    assert weak_components(db.for_tenant(b.tenant_id), foreign, limit=1)["truncated"]


def test_production_empty_and_remote_peer_cannot_expose_demo(release_service):
    _, db, _, _ = release_service
    for token in ("", "change-me-admin"):
        with pytest.raises(RuntimeError, match="refusing to start"):
            create_app(db, Settings(_env_file=None, pedigree_env="production", pedigree_admin_token=token))
    settings = db.settings.model_copy(update={"pedigree_env": "production", "pedigree_admin_token": "synthetic-admin"})
    with_client = TestClient(create_app(db, settings), client=("203.0.113.7", 1234))
    try:
        client = with_client
        assert client.get("/v1/ui/config").json() == {"demo_login": False, "api_docs": False}
        assert client.get("/docs").status_code == 404
    finally:
        with_client.close()
    local = settings.model_copy(update={"pedigree_env": "local", "pedigree_demo_login": True})
    with_client = TestClient(create_app(db, local), client=("203.0.113.7", 1234))
    try:
        client = with_client
        result = client.get("/v1/ui/config", headers={"X-Forwarded-For": "127.0.0.1"})
        assert result.json()["demo_login"] is False
        assert result.headers["cache-control"] == "no-store"
        assert client.post("/v1/demo/session", headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 403
    finally:
        with_client.close()


def test_wcc_excludes_metadata_as_connectivity_bridges(release_service):
    client, db, _, (a, _) = release_service
    graph = graph_name(a.tenant_id)
    body = {"runtime": "generic", "session_id": "session", "events": [
        {"type": "session"},
        {"type": "action_executed", "id": "a", "tool": "Read", "relied_on": ["session"]},
        {"type": "action_executed", "id": "b", "tool": "Read", "relied_on": ["session"]}]}
    response = client.post("/v1/events", headers=headers(a), json=body)
    assert response.status_code == 200, response.text
    result = weak_components(db, graph)
    assert sorted(c["nodes"] for c in result["components"]) == [1, 1], result


def test_admin_redis_rename_replaces_existing_graph(release_service):
    """Consult 014's absent GRAPH.RENAME is not proof Redis RENAME is absent.

    This probes a primitive, not a checkpoint/restore implementation or crash proof.
    """
    _, db, _, (a, _) = release_service
    source = graph_name(a.tenant_id) + ":ck:rename_source"
    target = graph_name(a.tenant_id) + ":ck:rename_target"
    db.query(source, "CREATE (:Node:Source {id:'new'})")
    db.query(target, "CREATE (:Node:Source {id:'old'})")
    scoped = db.for_tenant(a.tenant_id).client.connection
    with pytest.raises((NoPermissionError, ResponseError)):
        scoped.execute_command("RENAME", source, target)
    assert db.client.connection.execute_command("RENAME", source, target)
    assert db.ro_query(target, "MATCH(n) RETURN n.id").result_set == [["new"]]
    assert not db.client.connection.exists(source)
    assert source not in db.list_graphs() and target in db.list_graphs()
