"""Stored credential roles must bound public mutation authority (real FalkorDB)."""
import asyncio
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings
from pedigree.engine.ingest import record_source, remember
from pedigree.mcp_server import build_mcp


@pytest.fixture
def boundary(fresh_graph):
    db, tenant, graph = fresh_graph
    settings = Settings(pedigree_admin_token="roles-fixture-global-admin")
    registry = TenantRegistry(db, settings)
    credential = registry.create_tenant(tenant)
    record_source(db, graph, tenant, id="root", kind="web")
    remember(db, graph, tenant, id="belief", text="claim")
    try:
        with TestClient(create_app(db, settings)) as client:
            yield db, tenant, graph, registry, credential, client, settings
    finally:
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})


def bearer(token):
    return {"Authorization": "Bearer " + token}


def test_creation_issues_two_independent_stored_roles(boundary):
    db, tenant, _, registry, cred, _, _ = boundary
    assert hasattr(cred, "agent_token") and hasattr(cred, "operator_token")
    assert cred.token == cred.agent_token
    assert cred.agent_token.startswith("ped_a_") and cred.operator_token.startswith("ped_o_")
    assert registry.resolve(cred.agent_token).role == "agent"
    assert registry.resolve(cred.operator_token).role == "operator"
    rows = db.ro_query(registry.gname, "MATCH(t:Tenant {id:$id}) RETURN properties(t)", {"id": tenant}).result_set
    assert cred.agent_token not in str(rows) and cred.operator_token not in str(rows)


@pytest.mark.parametrize("path", ["revoke", "reinstate"])
def test_agent_cannot_change_revocation_state(boundary, path):
    _, _, _, _, cred, client, _ = boundary
    response = client.post("/v1/" + path, headers=bearer(cred.token), json={"root_id": "root"})
    assert response.status_code == 403, response.text


def test_global_admin_cannot_elevate_agent_bearer(boundary):
    _, _, _, _, cred, client, settings = boundary
    response = client.post("/v1/corroborate", headers={**bearer(cred.token), "X-Admin-Token": settings.pedigree_admin_token},
                           json={"memory_id": "belief", "source_id": "root", "by": "human"})
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("kind,integrity", [("human", None), ("scanner", None), ("web", "trusted")])
def test_agent_trust_claims_forbidden(boundary, kind, integrity):
    _, _, _, _, cred, client, _ = boundary
    payload = {"kind": kind, "id": "forged"}
    if integrity:
        payload["integrity"] = integrity
    response = client.post("/v1/sources", headers=bearer(cred.token), json=payload)
    assert response.status_code == 403, response.text


def test_events_authorize_entire_batch_before_writes(boundary):
    db, _, graph, _, cred, client, _ = boundary
    before = db.ro_query(graph, "MATCH(n) RETURN count(n)").result_set
    response = client.post("/v1/events", headers=bearer(cred.token), json={"events": [
        {"type": "memory", "text": "must not commit", "id": "early"},
        {"type": "source", "kind": "web", "integrity": "trusted", "id": "late"}]})
    assert response.status_code == 403, response.text
    assert db.ro_query(graph, "MATCH(n) RETURN count(n)").result_set == before


@pytest.mark.parametrize("kind", ["file", "rules_file", "user_prompt"])
def test_agent_can_capture_ordinary_untrusted_context(boundary, kind):
    _, _, _, _, cred, client, _ = boundary
    response = client.post("/v1/sources", headers=bearer(cred.token), json={"kind": kind})
    assert response.status_code == 200, response.text
    assert response.json()["low_integrity"] is True


def test_operator_allowed_and_prefix_forgery_denied(boundary):
    _, _, _, registry, cred, client, _ = boundary
    assert registry.resolve(cred.agent_token.replace("ped_a_", "ped_o_", 1)) is None
    for path in ("revoke", "reinstate"):
        response = client.post("/v1/" + path, headers=bearer(cred.operator_token), json={"root_id": "root"})
        assert response.status_code == 200, response.text
    response = client.post("/v1/sources", headers=bearer(cred.operator_token), json={"kind": "human", "integrity": "trusted"})
    assert response.status_code == 200, response.text
    assert response.json()["low_integrity"] is False


def test_legacy_digest_is_agent_only_and_operator_recovery_explicit(boundary):
    db, tenant, _, registry, _, client, _ = boundary
    legacy = "ped_" + tenant + "_legacy-fixture"
    db.query(registry.gname, "MATCH(t:Tenant {id:$id}) SET t.token_sha256=$sha,t.agent_token_sha256=NULL,t.operator_token_sha256=NULL",
             {"id": tenant, "sha": hashlib.sha256(legacy.encode()).hexdigest()})
    registry.invalidate_cache()
    assert registry.resolve(legacy).role == "agent"
    response = client.post("/v1/revoke", headers=bearer(legacy), json={"root_id": "root"})
    assert response.status_code == 403
    operator = registry.issue_operator(tenant)
    assert registry.resolve(operator).role == "operator"
    from pedigree.errors import Conflict
    with pytest.raises(Conflict):
        registry.issue_operator(tenant)
    replacement = registry.issue_operator(tenant, rotate=True)
    assert registry.resolve(operator) is None
    assert registry.resolve(replacement).role == "operator"
    registry.revoke_tenant(tenant)
    assert registry.resolve(replacement) is None


def test_mcp_explicit_roles_and_agent_only_defaults(boundary):
    db, tenant, _, _, cred, _, settings = boundary
    async def run():
        server = build_mcp(db, settings, tenant, cred.agent_token).server
        for token, expected in ((cred.agent_token, "forbidden"), (cred.operator_token, None)):
            result = await server.call_tool("pedigree_revoke", {"token": token, "root_id": "root"})
            payload = json.loads(result.content[0].text)
            if expected:
                assert payload["error"]["code"] == expected
            else:
                assert payload["ok"] is True
        configured = build_mcp(db, settings, tenant, cred.operator_token).server
        result = await configured.call_tool("pedigree_report", {})
        assert json.loads(result.content[0].text)["error"]["code"] == "unauthorized"
    asyncio.run(run())


def test_concurrent_operator_issuance_returns_only_one_valid_credential(boundary):
    db, tenant, _, registry, _, _, _ = boundary
    db.query(registry.gname, "MATCH(t:Tenant {id:$id}) SET t.operator_token_sha256=NULL", {"id": tenant})
    barrier = threading.Barrier(8)
    from pedigree.errors import Conflict
    def attempt(_):
        barrier.wait(10)
        try:
            return registry.issue_operator(tenant)
        except Conflict:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(attempt, range(8)))
    issued = [value for value in outcomes if value is not None]
    assert len(issued) == 1
    assert registry.resolve(issued[0]).role == "operator"


def test_concurrent_tenant_create_cannot_replace_credentials(db):
    import uuid

    from pedigree.errors import Conflict
    tenant = "rolecreate" + uuid.uuid4().hex[:10]
    registry = TenantRegistry(db)
    barrier = threading.Barrier(6)
    def attempt(_):
        barrier.wait(10)
        try:
            return registry.create_tenant(tenant)
        except Conflict:
            return None
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            outcomes = list(pool.map(attempt, range(6)))
        issued = [value for value in outcomes if value is not None]
        assert len(issued) == 1
        assert registry.resolve(issued[0].agent_token).role == "agent"
        assert registry.resolve(issued[0].operator_token).role == "operator"
        assert len(db.ro_query(registry.gname, "MATCH(t:Tenant {id:$id}) RETURN t.id", {"id": tenant}).result_set) == 1
    finally:
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})
