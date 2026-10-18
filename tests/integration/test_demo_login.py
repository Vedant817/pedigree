"""Local demo login returns the agent credential only, and only on this machine."""

from __future__ import annotations

import json
import uuid

from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.config import Settings


def _settings(tmp_path, tenant, enabled):
    return Settings(
        _env_file=None,
        pedigree_admin_token="demo-login-admin",
        pedigree_demo_login=enabled,
        pedigree_demo_tenant=tenant,
        pedigree_credentials_dir=str(tmp_path),
    )


def _drop(app, tenant):
    db = app.state.db
    registry = app.state.registry
    graph = "ped:" + tenant
    try:
        if graph in db.list_graphs():
            db.select(graph).delete()
    finally:
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})


def test_demo_login_is_hidden_until_enabled(tmp_path):
    tenant = "d" + uuid.uuid4().hex[:10]
    app = create_app(settings=_settings(tmp_path, tenant, False))
    try:
        response = TestClient(app).post("/v1/demo/session")
        assert response.status_code == 404
        assert "token" not in response.text
    finally:
        _drop(app, tenant)


def test_demo_login_returns_the_agent_credential_only(tmp_path):
    tenant = "d" + uuid.uuid4().hex[:10]
    app = create_app(settings=_settings(tmp_path, tenant, True))
    credential = app.state.registry.create_tenant(tenant)
    (tmp_path / f"demo-{tenant}.json").write_text(json.dumps({
        "tenant": tenant,
        "agent_token": credential.agent_token,
        "operator_token": credential.operator_token,
    }), encoding="utf-8")
    local = TestClient(app)
    remote = TestClient(app, client=("203.0.113.8", 40000))
    try:
        denied = remote.post("/v1/demo/session")
        assert denied.status_code == 403
        assert credential.agent_token not in denied.text
        assert credential.operator_token not in denied.text
        opened = local.post("/v1/demo/session")
        assert opened.status_code == 200, opened.text
        body = opened.json()
        assert body == {"tenant": tenant, "role": "agent", "token": credential.agent_token}
        assert credential.operator_token not in opened.text
        view = local.get("/v1/graph/view", headers={"Authorization": "Bearer " + body["token"]})
        assert view.status_code == 200
        revoke = local.post("/v1/revoke", headers={"Authorization": "Bearer " + body["token"]},
                            json={"root_id": "missing", "reason": "no"})
        assert revoke.status_code == 403
        page = local.get("/")
        script = local.get("/app.js")
        assert page.status_code == 200 and "Open the local demo" in page.text
        assert credential.agent_token not in page.text
        assert credential.agent_token not in script.text
    finally:
        _drop(app, tenant)


def test_demo_login_without_a_credential_file_stays_closed(tmp_path):
    tenant = "d" + uuid.uuid4().hex[:10]
    app = create_app(settings=_settings(tmp_path, tenant, True))
    try:
        response = TestClient(app).post("/v1/demo/session")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_in_graph"
    finally:
        _drop(app, tenant)
