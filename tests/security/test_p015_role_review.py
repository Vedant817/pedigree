"""Independent role-boundary QA; all data and coordination keys are fixture-owned."""
import asyncio
import hashlib
import json
import multiprocessing

import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings, graph_name
from pedigree.db.client import Db
from pedigree.db.schema import ensure_schema
from pedigree.engine.ingest import record_source, remember
from pedigree.engine.quota import lock_key
from pedigree.mcp_server import build_mcp


class HiddenHeaders(dict):
    def __repr__(self):
        return "<role-review headers>"


def bearer(token, **extra):
    return HiddenHeaders({"Authorization": "Bearer " + token, **extra})


def snapshot(db, graph):
    return (
        db.ro_query(graph, "MATCH(n) RETURN labels(n),properties(n) ORDER BY n.id").result_set,
        db.ro_query(graph, "MATCH(a)-[r]->(b) RETURN a.id,type(r),b.id,properties(r) ORDER BY a.id,b.id,type(r)").result_set,
    )


@pytest.fixture
def roles(fresh_graph):
    db, tenant, graph = fresh_graph
    settings = Settings(pedigree_admin_token="role-review-local-admin")
    registry = TenantRegistry(db, settings)
    credential = registry.create_tenant(tenant)
    record_source(db, graph, tenant, id="root", kind="web", uri="local-review")
    remember(db, graph, tenant, id="belief", derived_from=["root"])
    client = TestClient(create_app(db, settings))
    try:
        yield db, tenant, graph, registry, credential, client, settings
    finally:
        client.close()
        db.client.connection.delete(lock_key(graph))
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})


@pytest.mark.parametrize("claim", [{"kind": "human"}, {"kind": "scanner"}, {"kind": "web", "integrity": "trusted"}])
def test_review_late_event_claim_preserves_exact_existing_graph(roles, claim):
    db, _, graph, _, credential, client, settings = roles
    before = snapshot(db, graph)
    response = client.post("/v1/events", headers=bearer(credential.agent_token, **{"X-Admin-Token": settings.pedigree_admin_token}),
                           json={"events": [
                               {"type": "session", "session_id": "early_session"},
                               {"type": "source", "id": "early_source", "uri": "early"},
                               {"type": "memory", "id": "early_memory", "derived_from": ["root"]},
                               {"type": "source", "id": "late", **claim}]})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert snapshot(db, graph) == before
    assert not db.client.connection.exists(lock_key(graph))


def test_review_global_admin_never_elevates_agent_on_any_privileged_rest_path(roles):
    db, _, graph, _, credential, client, settings = roles
    before = snapshot(db, graph)
    headers = bearer(credential.agent_token, **{"X-Admin-Token": settings.pedigree_admin_token})
    for path, body in [
        ("revoke", {"root_id": "root"}), ("reinstate", {"root_id": "root"}),
        ("corroborate", {"memory_id": "belief", "source_id": "root", "by": "scanner"}),
        ("sources", {"kind": "web", "integrity": "trusted"}),
    ]:
        response = client.post("/v1/" + path, headers=headers, json=body)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"
        assert snapshot(db, graph) == before


def test_review_agent_denial_precedes_busy_quota_admission(roles):
    db, tenant, graph, _, credential, client, settings = roles
    key = lock_key(graph)
    assert db.client.connection.set(key, "role-review-owned-busy", nx=True)
    before = snapshot(db, graph)
    response = client.post("/v1/revoke", headers=bearer(credential.agent_token), json={"root_id": "root"})
    assert response.status_code == 403
    server = build_mcp(db, settings, tenant, credential.agent_token).server
    assert invoke(server, "pedigree_revoke", root_id="root")["error"]["code"] == "forbidden"
    assert db.client.connection.get(key) in (b"role-review-owned-busy", "role-review-owned-busy")
    assert snapshot(db, graph) == before


def test_review_legacy_and_digest_slot_role_binding(roles):
    db, tenant, graph, registry, credential, client, _ = roles
    before = snapshot(db, graph)
    # Give a syntactically operator credential only a legacy stored digest.
    db.query(registry.gname, "MATCH(t:Tenant {id:$id}) SET t.token_sha256=$sha,t.agent_token_sha256=NULL,t.operator_token_sha256=NULL",
             {"id": tenant, "sha": hashlib.sha256(credential.operator_token.encode()).hexdigest()})
    registry.invalidate_cache()
    assert registry.resolve(credential.operator_token) is None
    legacy = "ped_" + tenant + "_independent-legacy-fixture"
    db.query(registry.gname, "MATCH(t:Tenant {id:$id}) SET t.token_sha256=$sha",
             {"id": tenant, "sha": hashlib.sha256(legacy.encode()).hexdigest()})
    assert registry.resolve(legacy).role == "agent"
    assert client.post("/v1/revoke", headers=bearer(legacy), json={"root_id": "root"}).status_code == 403
    # An agent-shaped credential placed in the operator slot is rejected, not promoted.
    db.query(registry.gname, "MATCH(t:Tenant {id:$id}) SET t.operator_token_sha256=$sha",
             {"id": tenant, "sha": hashlib.sha256(credential.agent_token.encode()).hexdigest()})
    assert registry.resolve(credential.agent_token) is None
    assert snapshot(db, graph) == before


def _rotate_or_revoke(settings, tenant, queue, operation):
    registry = TenantRegistry(Db(settings))
    if operation == "rotate":
        queue.put(registry.issue_operator(tenant, rotate=True))
    else:
        registry.revoke_tenant(tenant)
        queue.put(True)


def test_review_cache_revalidates_after_separate_process_rotation_and_revocation(roles):
    db, tenant, _, registry, credential, _, _ = roles
    assert registry.resolve(credential.operator_token).role == "operator"
    assert registry.resolve(credential.agent_token).role == "agent"
    context = multiprocessing.get_context("spawn")
    for operation in ("rotate", "revoke"):
        queue = context.Queue()
        worker = context.Process(target=_rotate_or_revoke, args=(db.settings, tenant, queue, operation))
        try:
            worker.start()
            result = queue.get(timeout=30)
            worker.join(10)
            assert worker.exitcode == 0
            if operation == "rotate":
                assert registry.resolve(credential.operator_token) is None
                assert registry.resolve(result).role == "operator"
                assert registry.resolve(credential.agent_token).role == "agent"
                replacement = result
            else:
                assert result is True
                assert registry.resolve(replacement) is None
                assert registry.resolve(credential.agent_token) is None
        finally:
            if worker.is_alive():
                worker.terminate()
                worker.join(10)
            queue.close()


def invoke(server, name, **arguments):
    result = asyncio.run(server.call_tool(name, arguments))
    return json.loads(result.content[0].text)


def test_review_operator_rest_and_explicit_mcp_positive_with_default_denial(roles):
    db, tenant, graph, _, credential, client, settings = roles
    headers = bearer(credential.operator_token)
    response = client.post("/v1/sources", headers=headers,
                           json={"kind": "human", "integrity": "trusted", "id": "trusted"})
    assert response.status_code == 200
    assert response.json()["low_integrity"] is False
    server = build_mcp(db, settings, tenant, credential.agent_token).server
    assert invoke(server, "pedigree_corroborate", token=credential.operator_token,
                  memory_id="belief", source_id="trusted", by="human")["ok"]
    assert invoke(server, "pedigree_revoke", token=credential.operator_token, root_id="root")["ok"]
    assert client.post("/v1/reinstate", headers=headers, json={"root_id": "root"}).status_code == 200
    before = snapshot(db, graph)
    configured = build_mcp(db, settings, tenant, credential.operator_token).server
    assert invoke(configured, "pedigree_revoke", root_id="root")["error"]["code"] == "unauthorized"
    assert invoke(server, "pedigree_revoke", token="", root_id="root")["error"]["code"] == "unauthorized"
    assert invoke(server, "pedigree_revoke", root_id="root")["error"]["code"] == "forbidden"
    assert snapshot(db, graph) == before


def test_review_operator_cannot_cross_tenant_or_list_global_registry(roles):
    db, tenant, graph, registry, credential, client, settings = roles
    # Separate graph/id owned locally; the shared fresh_graph fixture is the primary.
    import uuid
    other = "rolereview" + uuid.uuid4().hex[:10]
    other_graph = graph_name(other)
    registry.create_tenant(other)
    try:
        ensure_schema(db, other_graph)
        record_source(db, other_graph, other, kind="web", id="foreign_root")
        before = snapshot(db, other_graph)
        assert client.post("/v1/revoke", headers=bearer(credential.operator_token),
                           json={"root_id": "foreign_root"}).status_code == 404
        server = build_mcp(db, settings, tenant, credential.agent_token).server
        assert invoke(server, "pedigree_revoke", token=credential.operator_token,
                      tenant_id=other, root_id="foreign_root")["error"]["code"] == "unauthorized"
        assert client.get("/admin/tenants", headers=bearer(credential.operator_token)).status_code == 401
        assert snapshot(db, other_graph) == before
        assert snapshot(db, graph)[0]
    finally:
        db.client.connection.delete(lock_key(other_graph))
        db.select(other_graph).delete()
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": other})


def test_review_sdk_http_header_precedence_and_per_request_role_isolation(roles):
    db, tenant, graph, _, credential, _, settings = roles
    wrapper = build_mcp(db, settings, tenant, credential.agent_token)
    # Actual installed SDK HTTP-ASGI transport, stateless JSON responses; no fake headers ContextVar.
    app = wrapper.server.streamable_http_app(stateless_http=True, json_response=True)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        def call(headers, **arguments):
            response = client.post("/mcp", headers={"Accept": "application/json, text/event-stream",
                                  "MCP-Protocol-Version": "2025-11-25", **headers},
                                   json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                         "params": {"name": "pedigree_revoke", "arguments": {"root_id": "root", **arguments}}})
            assert response.status_code == 200
            return json.loads(response.json()["result"]["content"][0]["text"])

        before = snapshot(db, graph)
        for invalid in ("", "Basic bad", "Bearer garbage", "Bearer  " + credential.operator_token):
            assert call(HiddenHeaders({"Authorization": invalid}), token=credential.operator_token)["error"]["code"] == "unauthorized"
        assert call(bearer(credential.agent_token), token=credential.operator_token)["error"]["code"] == "unauthorized"
        assert call(bearer(credential.agent_token))["error"]["code"] == "forbidden"
        assert snapshot(db, graph) == before
        assert call(bearer(credential.operator_token))["ok"]
        after = snapshot(db, graph)
        assert call(bearer(credential.agent_token))["error"]["code"] == "forbidden"
        assert snapshot(db, graph) == after
