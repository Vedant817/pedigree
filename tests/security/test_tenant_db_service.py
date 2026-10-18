"""Real service-scoped credentials, including direct Redis attack attempts."""
import asyncio
import json
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st
from redis.exceptions import NoPermissionError, ResponseError

from pedigree.api.app import create_app
from pedigree.config import Settings, graph_name
from pedigree.db.client import Db
from pedigree.errors import Forbidden, Unavailable
from pedigree.mcp_server import build_mcp


@pytest.fixture
def service(monkeypatch):
    settings = Settings(pedigree_db_acl=True, pedigree_db_acl_secret=secrets.token_urlsafe(32))
    admin = Db(settings)
    app = create_app(db=admin, settings=settings)
    registry = app.state.registry
    tenants = ["acl" + uuid.uuid4().hex[:10] for _ in range(2)]
    credentials = [registry.create_tenant(t) for t in tenants]
    try:
        with TestClient(app) as client:
            yield client, admin, registry, credentials
    finally:
        for tenant in tenants:
            for name in admin.list_graphs():
                if name == graph_name(tenant) or name.startswith(graph_name(tenant) + ":"):
                    admin.select(name).delete()
            admin.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})
            admin.execute_admin("ACL", "DELUSER", "t_" + tenant)


def test_real_scoped_service_client_denies_foreign_graphs_and_coordination(service):
    client, admin, registry, (a, b) = service
    headers = {"Authorization": "Bearer " + a.operator_token}
    response = client.post("/v1/sources", headers=headers,
                           json={"id": "source", "kind": "web", "uri": "https://example.org/a"})
    assert response.status_code == 200, response.text
    scoped = admin.for_tenant(a.tenant_id)
    assert scoped.settings.falkor_username == "t_" + a.tenant_id
    assert scoped.ro_query(graph_name(a.tenant_id), "MATCH(n:Source) RETURN n.id").result_set == [["source"]]
    for foreign in (graph_name(b.tenant_id), registry.gname, "pedigree:registry"):
        with pytest.raises((NoPermissionError, ResponseError)):
            scoped.client.select_graph(foreign).ro_query("RETURN 1")
        with pytest.raises((NoPermissionError, ResponseError)):
            scoped.client.select_graph(graph_name(a.tenant_id)).copy(foreign + ":wi:bad")
    for command in (("GRAPH.LIST",), ("ACL", "LIST"),
                    ("SET", "pedigree:quota:mutex:" + graph_name(b.tenant_id), "x")):
        with pytest.raises((NoPermissionError, ResponseError)):
            scoped.client.connection.execute_command(*command)
    with pytest.raises(Forbidden):
        scoped.select(graph_name(b.tenant_id))
    assert client.get("/v1/graph/view", headers=headers).status_code == 200
    assert client.post("/v1/whatif", headers=headers, json={"roots": ["source"]}).status_code == 200
    assert client.post("/v1/revoke", headers=headers, json={"root_id": "source", "reason": "test"}).status_code == 200
    assert client.post("/v1/reinstate", headers=headers, json={"root_id": "source"}).status_code == 200


def test_provisioning_failure_never_returns_administrator(service, monkeypatch):
    client, admin, _, (a, _) = service
    def fail(*args):
        raise Unavailable("injected provisioning failure")
    with monkeypatch.context() as patch:
        patch.setattr(admin, "execute_admin", fail)
        with pytest.raises(Unavailable):
            admin.for_tenant(a.tenant_id)
        response = client.get("/v1/graph", headers={"Authorization": "Bearer " + a.agent_token})
        assert response.status_code == 503


def test_deleted_acl_user_is_reprovisioned_without_admin_engine_fallback(service):
    client, admin, _, (a, _) = service
    headers = {"Authorization": "Bearer " + a.agent_token}
    assert client.get("/v1/graph", headers=headers).status_code == 200
    admin.execute_admin("ACL", "DELUSER", "t_" + a.tenant_id)
    assert client.get("/v1/graph", headers=headers).status_code == 200


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=3, max_size=24))
def test_scoped_namespace_guard_rejects_prefix_confusion(tenant):
    if tenant == "registry":
        return
    from pedigree.db.client import tenant_graph_allowed
    base = graph_name(tenant)
    assert tenant_graph_allowed(tenant, base)
    assert tenant_graph_allowed(tenant, base + ":wi:1234abcd")
    assert tenant_graph_allowed(tenant, base + ":ck:snapshot")
    assert not tenant_graph_allowed(tenant, base + "x")
    assert not tenant_graph_allowed(tenant, "ped:registry")
    assert not tenant_graph_allowed(tenant, base + ":wi:../other")


def test_disabled_acl_mode_remains_explicitly_compatible():
    admin = Db(Settings(pedigree_db_acl=False))
    assert admin.for_tenant("abc") is admin


def test_rest_and_mcp_engines_never_use_administrator_connection(service, monkeypatch):
    client, admin, registry, (a, _) = service
    server = build_mcp(admin, admin.settings).server
    original = admin.select

    def registry_only(gname):
        assert gname == registry.gname, "tenant operation used administrator connection"
        return original(gname)

    with monkeypatch.context() as patch:
        patch.setattr(admin, "select", registry_only)
        headers = {"Authorization": "Bearer " + a.agent_token}
        assert client.post("/v1/sources", headers=headers,
                           json={"id": "captured", "kind": "file", "uri": "local-test"}).status_code == 200
        assert client.post("/v1/events", headers=headers,
                           json={"runtime": "claude-code", "session_id": "session", "events": []}).status_code == 200
        for route in ("/v1/graph", "/v1/graph/view", "/v1/invariants", "/v1/artifacts/lookup?key=local-test"):
            response = client.get(route, headers=headers)
            assert response.status_code == 200, response.text
        assert client.post("/v1/gate", headers=headers,
                           json={"action": {"tool": "Read", "summary": "read"}, "relied_on": ["captured"]}).status_code == 200

        async def invoke():
            result = await server.call_tool("pedigree_record_source", {
                "token": a.agent_token, "kind": "web", "id": "mcp", "uri": "https://example.org/mcp"})
            return json.loads(result.content[0].text)

        assert asyncio.run(invoke())["ok"] is True


def test_startup_recovery_uses_scoped_connections(service, monkeypatch):
    from pedigree.api.app import _startup_resume
    client, admin, registry, (a, b) = service
    seen = []

    def resume(db, graph):
        assert db is not admin
        assert db.settings.falkor_username == "t_" + db._tenant
        assert graph == graph_name(db._tenant)
        seen.append(graph)
        return []

    monkeypatch.setattr("pedigree.engine.revoke.resume_incomplete", resume)
    _startup_resume(admin, registry)
    assert {graph_name(a.tenant_id), graph_name(b.tenant_id)} <= set(seen)


def test_production_acl_requires_dedicated_secret():
    db = Db(Settings(pedigree_env="production", pedigree_db_acl=True, pedigree_db_acl_secret=""))
    with pytest.raises(Unavailable, match="deployment secret"):
        db.for_tenant("abc")


def test_deployment_admin_resume_still_uses_tenant_database_identity(service, monkeypatch):
    client, admin, registry, (a, _) = service
    client.app.state.settings.pedigree_admin_token = "recovery-test-admin"
    original = admin.select
    def registry_only(gname):
        assert gname == registry.gname, "resume used administrator for tenant graph"
        return original(gname)
    monkeypatch.setattr(admin, "select", registry_only)
    response = client.post("/v1/admin/resume", json={"tenant": a.tenant_id},
                           headers={"X-Admin-Token": "recovery-test-admin"})
    assert response.status_code == 200, response.text
