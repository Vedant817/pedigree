"""P-020 real indexed registry admission, without real-registry bulk fixtures."""
from __future__ import annotations

import hashlib
import statistics
import time
import uuid

import pytest

from pedigree.api.registry import TenantRegistry
from pedigree.config import get_settings
from pedigree.db import queries as Q
from pedigree.db.schema import ensure_schema

SLOTS = ("agent_token_sha256", "operator_token_sha256", "token_sha256")


@pytest.fixture
def isolated_registry(db):
    name = "p020_registry_" + uuid.uuid4().hex
    ensure_schema(db, name, label="Tenant")
    registry = object.__new__(TenantRegistry)
    registry.db = db
    registry.settings = get_settings()
    registry.gname = name
    try:
        yield registry
    finally:
        db.select(name).delete()
        names = [n.decode() if isinstance(n, bytes) else n for n in db.admin_raw("GRAPH.LIST")]
        assert name not in names


@pytest.mark.parametrize("size", [31, 1001])
def test_miss_and_hit_have_one_live_lookup(isolated_registry, monkeypatch, size):
    registry = isolated_registry
    credential = registry.create_tenant("known")
    rows = [{"id": "synthetic" + str(i), "sha": hashlib.sha256(str(i).encode()).hexdigest()}
            for i in range(size - 1)]
    registry.db.query(registry.gname, '''UNWIND $rows AS row
        CREATE(:Tenant {id:row.id,agent_token_sha256:row.sha,status:'active',node_cap:100,created_at:1})''', {"rows": rows})
    plan = str(registry.db.select(registry.gname).explain(Q.Q_REGISTRY_BY_DIGEST,
        {"sha": hashlib.sha256(b"synthetic-miss").hexdigest()}))
    assert "Node By Index Scan" in plan
    original = registry.db.ro_query
    calls = []

    def observed(graph, query, *args, **kwargs):
        if graph == registry.gname:
            calls.append(query)
        return original(graph, query, *args, **kwargs)

    monkeypatch.setattr(registry.db, "ro_query", observed)
    for token, expected in [("ped_a_missing_synthetic", False), (credential.agent_token, True)]:
        calls.clear()
        principal = registry.resolve(token)
        assert (principal is not None) is expected
        assert len(calls) == 1
        assert Q.Q_REGISTRY_ALL not in calls
        assert calls[0] == Q.Q_REGISTRY_BY_DIGEST
    samples = []
    for _ in range(25):
        started = time.perf_counter()
        principal = registry.resolve("ped_a_missing_synthetic")
        samples.append(time.perf_counter() - started)
        assert principal is None
    median_ms = statistics.median(samples) * 1000
    print(f"[indexed-auth] rows={size} median_miss_ms={median_ms:.3f}")
    # Local acceptance threshold, not a maximum latency or production guarantee.
    assert median_ms < 10


def test_digest_indexes_are_operational_and_lookup_plan_is_indexed(isolated_registry):
    registry = isolated_registry
    digest = hashlib.sha256(b"synthetic-miss").hexdigest()
    for query in [Q.Q_REGISTRY_BY_DIGEST, *(f"MATCH(t:Tenant {{{slot}:$sha}}) RETURN t.id" for slot in SLOTS)]:
        plan = str(registry.db.select(registry.gname).explain(query, {"sha": digest}))
        assert "Node By Index Scan" in plan
        assert "Label Scan" not in plan


def test_duplicate_digest_candidates_are_refused(isolated_registry):
    registry = isolated_registry
    credential = registry.create_tenant("owner")
    registry.db.query(registry.gname, '''CREATE(:Tenant {id:'ambiguous',status:'active',
        node_cap:100,created_at:1,operator_token_sha256:$sha})''',
        {"sha": hashlib.sha256(credential.agent_token.encode()).hexdigest()})
    principal = registry.resolve(credential.agent_token)
    assert principal is None


def test_roles_nullable_legacy_slots_and_live_authority(isolated_registry):
    registry = isolated_registry
    credential = registry.create_tenant("roles")
    agent = registry.resolve(credential.agent_token)
    operator = registry.resolve(credential.operator_token)
    assert agent.role == "agent"
    assert operator.role == "operator"
    legacy = "ped_old_synthetic-legacy-credential"
    registry.db.query(registry.gname, '''CREATE(:Tenant {id:'old',status:'active',node_cap:100,
        created_at:1,token_sha256:$sha})''', {"sha": hashlib.sha256(legacy.encode()).hexdigest()})
    assert registry.resolve(legacy).role == "agent"
    # A stored digest alone must not override the complete tenant prefix.
    wrong_prefix = "ped_o_other_synthetic"
    registry.db.query(registry.gname, '''CREATE(:Tenant {id:'different',status:'active',node_cap:100,
        created_at:1,operator_token_sha256:$sha})''', {"sha": hashlib.sha256(wrong_prefix.encode()).hexdigest()})
    assert registry.resolve(wrong_prefix) is None
    registry.revoke_tenant("roles")
    principal = registry.resolve(credential.agent_token)
    assert principal is None
    principal = registry.resolve(credential.operator_token)
    assert principal is None
