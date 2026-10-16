"""Independent P-015 adversarial probes; all graph operations use real FalkorDB."""
import asyncio
import hashlib
import importlib.util
import json
import socket
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import httpx2
import pytest
from fastapi.testclient import TestClient
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings
from pedigree.engine.ingest import record_source, remember
from pedigree.errors import Conflict
from pedigree.mcp_server import build_mcp


@pytest.fixture
def attack(fresh_graph):
    db, tenant, graph = fresh_graph
    settings = Settings(pedigree_admin_token="attack-fixture-admin")
    registry = TenantRegistry(db, settings)
    cred = registry.create_tenant(tenant)
    record_source(db, graph, tenant, id="poison", kind="web")
    record_source(db, graph, tenant, id="support", kind="human", integrity="trusted")
    remember(db, graph, tenant, id="belief", text="poisoned claim", derived_from=["poison"])
    try:
        with TestClient(create_app(db, settings)) as client:
            yield db, tenant, graph, registry, cred, client, settings
    finally:
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})


def auth(token):
    return {"Authorization": "Bearer " + token}


def snapshot(db, graph):
    return (db.ro_query(graph, "MATCH(n) RETURN labels(n),properties(n) ORDER BY n.id").result_set,
            db.ro_query(graph, "MATCH(a)-[r]->(b) RETURN a.id,type(r),b.id,properties(r) ORDER BY a.id,b.id").result_set)


def invoke(server, tool, **arguments):
    async def call():
        result = await server.call_tool(tool, arguments)
        return json.loads(result.content[0].text)
    return asyncio.run(call())


@pytest.mark.parametrize("channel", ["rest", "mcp"])
def test_laundering_cannot_change_tainted_state_or_gate(attack, channel):
    db, tenant, graph, _, cred, client, settings = attack
    assert client.post("/v1/revoke", headers=auth(cred.operator_token),
                       json={"root_id": "poison"}).status_code == 200
    before = snapshot(db, graph)
    gate = {"action": {"tool": "shell", "summary": "git push origin main", "risk": "high",
                       "effect": "irreversible"}, "relied_on": ["belief"]}
    assert client.post("/v1/gate", headers=auth(cred.agent_token), json=gate).json()["decision"] == "block"
    if channel == "rest":
        for by in ("human", "scanner"):
            response = client.post("/v1/corroborate", headers={**auth(cred.agent_token),
                "X-Admin-Token": settings.pedigree_admin_token},
                json={"memory_id": "belief", "source_id": "support", "by": by})
            assert response.status_code == 403
        response = client.post("/v1/sources", headers=auth(cred.agent_token),
                               json={"id": "forged", "kind": "human", "integrity": "trusted"})
        assert response.status_code == 403
    else:
        server = build_mcp(db, settings, tenant, cred.agent_token).server
        for by in ("human", "scanner"):
            result = invoke(server, "pedigree_corroborate", token=cred.agent_token,
                            memory_id="belief", source_id="support", by=by)
            assert result.get("error", {}).get("code") == "forbidden"
        result = invoke(server, "pedigree_record_source", token=cred.agent_token,
                        id="forged", kind="human", integrity="trusted")
        assert result.get("error", {}).get("code") == "forbidden"
    assert snapshot(db, graph) == before
    assert client.post("/v1/gate", headers=auth(cred.agent_token), json=gate).json()["decision"] == "block"


def test_agent_corroborated_by_cannot_become_trusted_support(attack):
    db, _, graph, _, cred, client, _ = attack
    response = client.post("/v1/memories", headers=auth(cred.agent_token), json={
        "id": "indirect", "text": "same claim", "derived_from": ["poison"], "corroborated_by": ["support"]})
    assert response.status_code == 200
    assert client.post("/v1/revoke", headers=auth(cred.operator_token),
                       json={"root_id": "poison"}).status_code == 200
    rows = db.ro_query(graph, "MATCH(m:Memory {id:'indirect'})-[r:CORROBORATED_BY]->() RETURN m.status,r.by").result_set
    # The graph preservation algorithm counts agent corroboration; the gate must
    # independently refuse to treat that descriptive status as trusted support.
    assert rows == [["preserved", "agent"]]
    gate = client.post("/v1/gate", headers=auth(cred.agent_token), json={
        "action": {"tool": "shell", "summary": "git push origin main", "risk": "high",
                   "effect": "irreversible"}, "relied_on": ["indirect"]})
    assert gate.status_code == 200
    assert gate.json()["decision"] == "block"


@pytest.mark.parametrize("role_action", ["revoke", "reinstate"])
def test_agent_state_mutation_mcp_denied_without_writes(attack, role_action):
    db, tenant, graph, _, cred, _, settings = attack
    server = build_mcp(db, settings, tenant, cred.agent_token).server
    before = snapshot(db, graph)
    result = invoke(server, "pedigree_" + role_action, root_id="poison", token=cred.agent_token)
    assert result.get("error", {}).get("code") == "forbidden"
    assert snapshot(db, graph) == before


def test_operator_positive_mcp_attestation_and_rest_reinstate(attack):
    db, tenant, graph, _, cred, client, settings = attack
    server = build_mcp(db, settings, tenant, cred.agent_token).server
    result = invoke(server, "pedigree_corroborate", token=cred.operator_token,
                    memory_id="belief", source_id="support", by="human")
    assert result.get("ok") is True
    result = invoke(server, "pedigree_revoke", token=cred.operator_token, root_id="poison")
    assert result.get("ok") is True
    assert db.ro_query(graph, "MATCH(m:Memory {id:'belief'}) RETURN m.status").result_set == [["preserved"]]
    assert client.post("/v1/reinstate", headers=auth(cred.operator_token),
                       json={"root_id": "poison"}).status_code == 200


def test_operator_cross_tenant_and_deployment_admin_denied(attack):
    db, _, graph, _, cred, client, settings = attack
    other = "attackmissing" + uuid.uuid4().hex[:10]
    server = build_mcp(db, settings).server
    before = snapshot(db, graph)
    result = invoke(server, "pedigree_revoke", tenant_id=other,
                    token=cred.operator_token, root_id="poison")
    assert result.get("error", {}).get("code") == "unauthorized"
    assert client.get("/admin/tenants", headers=auth(cred.operator_token)).status_code == 401
    assert snapshot(db, graph) == before


def test_legacy_prefix_and_stored_digest_cannot_forge_operator(attack):
    db, tenant, _, registry, cred, client, _ = attack
    legacy = "ped_" + tenant + "_syntheticlegacy"
    db.query(registry.gname, "MATCH(t:Tenant {id:$id}) SET t.token_sha256=$sha", {
        "id": tenant, "sha": hashlib.sha256(legacy.encode()).hexdigest()})
    assert registry.resolve(legacy).role == "agent"
    assert registry.resolve(cred.agent_token.replace("ped_a_", "ped_o_", 1)) is None
    assert client.post("/v1/revoke", headers=auth(legacy), json={"root_id": "poison"}).status_code == 403


def test_warmed_cache_other_process_rotation_and_revocation(attack):
    db, tenant, _, registry, cred, client, _ = attack
    assert registry.resolve(cred.operator_token).role == "operator"
    # CLI runs in a genuinely separate process and prints its credential to a pipe;
    # capture privately and never include the output in an assertion or report.
    process = subprocess.run([sys.executable, "-m", "pedigree.cli", "admin", "issue-operator",
                              "--id", tenant, "--rotate"], capture_output=True, text=True, timeout=20)
    assert process.returncode == 0, "owned rotation subprocess failed (output withheld)"
    replacement = json.loads(process.stdout)["operator_token"]
    assert registry.resolve(cred.operator_token) is None
    assert registry.resolve(replacement).role == "operator"
    assert client.post("/v1/revoke", headers=auth(cred.operator_token), json={"root_id": "poison"}).status_code == 401
    TenantRegistry(db).revoke_tenant(tenant)
    assert registry.resolve(replacement) is None
    assert client.post("/v1/revoke", headers=auth(replacement), json={"root_id": "poison"}).status_code == 401


def test_repeated_real_db_concurrent_operator_issuance(attack):
    db, tenant, _, registry, _, _, _ = attack
    for _ in range(4):
        db.query(registry.gname, "MATCH(t:Tenant {id:$id}) SET t.operator_token_sha256=NULL", {"id": tenant})
        barrier = threading.Barrier(12)
        def attempt(_, barrier=barrier):
            local = TenantRegistry(db)
            barrier.wait(10)
            try:
                return local.issue_operator(tenant)
            except Conflict:
                return None
        with ThreadPoolExecutor(max_workers=12) as pool:
            outcomes = list(pool.map(attempt, range(12)))
        issued = [value for value in outcomes if value is not None]
        assert len(issued) == 1, "issuance race returned multiple credentials (values withheld)"
        assert registry.resolve(issued[0]).role == "operator"


def test_repeated_tenant_create_cannot_replace_credentials(db):
    registry = TenantRegistry(db)
    for _ in range(4):
        tenant = "attackcreate" + uuid.uuid4().hex[:10]
        barrier = threading.Barrier(10)
        def attempt(_, barrier=barrier, tenant=tenant):
            local = TenantRegistry(db)
            barrier.wait(10)
            try:
                return local.create_tenant(tenant)
            except Conflict:
                return None
        try:
            with ThreadPoolExecutor(max_workers=10) as pool:
                results = list(pool.map(attempt, range(10)))
            issued = [value for value in results if value is not None]
            assert len(issued) == 1, "creation race returned multiple credentials (values withheld)"
            assert registry.resolve(issued[0].agent_token).role == "agent"
            assert registry.resolve(issued[0].operator_token).role == "operator"
            assert len(db.ro_query(registry.gname, "MATCH(t:Tenant {id:$id}) RETURN t.id",
                                   {"id": tenant}).result_set) == 1
        finally:
            db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})


@pytest.mark.parametrize("claim", [{"kind": "scanner"}, {"kind": "web", "integrity": "trusted"},
                                   {"kind": "web", "by": "human"}])
def test_denied_late_event_keeps_entire_batch_unchanged(attack, claim):
    db, _, graph, _, cred, client, settings = attack
    before = snapshot(db, graph)
    response = client.post("/v1/events", headers={**auth(cred.agent_token),
        "X-Admin-Token": settings.pedigree_admin_token}, json={"events": [
            {"type": "memory", "id": "early", "text": "must not be written"},
            {"type": "source", "id": "late", **claim}]})
    assert response.status_code == 403
    assert snapshot(db, graph) == before


def test_configured_operator_default_and_hook_are_refused(attack, monkeypatch):
    db, tenant, graph, _, cred, _, settings = attack
    server = build_mcp(db, settings, tenant, cred.operator_token).server
    before = snapshot(db, graph)
    result = invoke(server, "pedigree_record_source", kind="web", id="defaultforged")
    assert result.get("error", {}).get("code") == "unauthorized"
    path = Path(__file__).resolve().parents[2] / "adapters/claude/pedigree_hook.py"
    spec = importlib.util.spec_from_file_location("attack_hook", path)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    monkeypatch.setenv("PEDIGREE_TOKEN", cred.operator_token)
    with pytest.raises(ValueError, match="requires an agent token"):
        hook.request("/v1/gate", {})
    assert snapshot(db, graph) == before


@pytest.fixture
def attack_http(attack):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "pedigree.api.app:create_app", "--factory",
                               "--host", "127.0.0.1", "--port", str(port)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.1)
        else:
            pytest.fail("owned HTTP attack server did not become ready")
        yield attack, f"http://127.0.0.1:{port}/mcp"
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


async def http_invoke(url, headers, arguments):
    async with httpx2.AsyncClient(headers=headers) as http_client:
        async with Client(streamable_http_client(url, http_client=http_client)) as client:
            response = await client.call_tool("pedigree_revoke", arguments)
            return json.loads(response.content[0].text)


def test_real_http_conflict_invalid_fallback_and_context_isolation(attack_http):
    boundary, url = attack_http
    db, _, graph, _, cred, _, _ = boundary
    before = snapshot(db, graph)
    async def run():
        cases = [
            ({"Authorization": "Bearer invalid"}, {"token": cred.operator_token}, "unauthorized"),
            (auth(cred.agent_token), {"token": cred.operator_token}, "unauthorized"),
            (auth(cred.operator_token), {"token": cred.agent_token}, "unauthorized"),
            ([("Authorization", "Bearer " + cred.operator_token),
              ("Authorization", "Bearer " + cred.agent_token)], {}, "unauthorized"),
        ]
        for headers, arguments, expected in cases:
            result = await http_invoke(url, headers, {**arguments, "root_id": "poison", "dry_run": True})
            assert result.get("error", {}).get("code") == expected
        results = await asyncio.gather(*[
            http_invoke(url, auth(cred.operator_token if index % 2 else cred.agent_token),
                        {"root_id": "poison", "dry_run": True}) for index in range(10)])
        for index, result in enumerate(results):
            if index % 2:
                assert result.get("ok") is True
            else:
                assert result.get("error", {}).get("code") == "forbidden"
    asyncio.run(run())
    assert snapshot(db, graph) == before
