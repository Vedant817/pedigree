"""Captured source versions must preserve revocation and confidentiality across aliases."""
import uuid

import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings, graph_name
from pedigree.db.schema import ensure_schema
from pedigree.engine.ingest import record_source
from pedigree.engine.revoke import revoke
from pedigree.errors import Conflict


@pytest.fixture
def identity_boundary(fresh_graph):
    db, tenant, graph = fresh_graph
    settings = Settings(pedigree_admin_token="identity-test-operator")
    registry = TenantRegistry(db, settings)
    cred = registry.create_tenant(tenant)
    with TestClient(create_app(db, settings)) as client:
        try:
            yield db, tenant, graph, client, {"Authorization": "Bearer " + cred.token}, registry
        finally:
            db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": tenant})


@pytest.mark.parametrize("kind", ["file", "web"])
def test_same_capture_version_reuses_revoked_source(fresh_graph, kind):
    db, tenant, graph = fresh_graph
    first = record_source(db, graph, tenant, kind=kind, uri="file:///versioned", content_hash="a" * 64)
    same = record_source(db, graph, tenant, kind=kind, uri="file:///versioned", content_hash="a" * 64)
    assert same.id == first.id
    changed = record_source(db, graph, tenant, kind=kind, uri="file:///versioned", content_hash="b" * 64)
    assert changed.id != first.id
    revoke(db, graph, tenant, root_id=first.id)
    again = record_source(db, graph, tenant, kind=kind, uri="file:///versioned", content_hash="a" * 64)
    assert (again.id, again.status) == (first.id, "revoked")
    assert db.ro_query(graph, "MATCH (s:Source) RETURN count(s)").result_set == [[2]]


def test_hashless_read_converges_on_uri(fresh_graph):
    """A read without a content hash still converges: the uri names the source (ADR-008)."""
    db, tenant, graph = fresh_graph
    first = record_source(db, graph, tenant, kind="web", uri="http://example.com/x")
    again = record_source(db, graph, tenant, kind="web", uri="http://example.com/x")
    assert again.id == first.id
    assert db.ro_query(graph, "MATCH (s:Source) RETURN count(s)").result_set == [[1]]


def test_same_content_under_a_different_caller_id_converges(fresh_graph):
    """Identity comes from the artifact, not from the id a capture happened to use."""
    db, tenant, graph = fresh_graph
    first = record_source(db, graph, tenant, id="caller-first", kind="file",
                          uri="docs/rules.md", content_hash="a" * 64)
    second = record_source(db, graph, tenant, id="caller-second", kind="file",
                           uri="docs/rules.md", content_hash="a" * 64)
    assert second.id == first.id
    assert db.ro_query(graph, "MATCH (s:Source) RETURN count(s)").result_set == [[1]]


def test_caller_id_for_different_content_is_a_conflict(fresh_graph):
    db, tenant, graph = fresh_graph
    record_source(db, graph, tenant, id="taken", kind="file", uri="docs/a.md")
    with pytest.raises(Conflict):
        record_source(db, graph, tenant, id="taken", kind="file", uri="docs/b.md")


def post_events(client, headers, events):
    response = client.post("/v1/events", headers=headers,
                           json={"runtime": "claude-code", "session_id": "capture-session", "events": events})
    assert response.status_code == 200, response.text
    return response.json()["created"]


def test_authenticated_capture_ids_cannot_escape_revocation(identity_boundary):
    db, tenant, graph, client, headers, _ = identity_boundary
    common = {"type": "source", "kind": "file", "uri": "file:///secret", "content_hash": "a" * 64}
    first = post_events(client, headers, [{**common, "id": "caller-first", "conf": ["private"]}])[0]
    revoke(db, graph, tenant, root_id=first)
    second = post_events(client, headers, [{**common, "id": "caller-second", "conf": []}])[0]
    assert second == first
    rows = db.ro_query(graph, "MATCH (s:Source) RETURN s.status,s.conf_eff").result_set
    assert rows == [["revoked", ["private"]]]


def test_mixed_capture_aliases_resolve_reads_and_derived_confidentiality(identity_boundary):
    db, _, graph, client, headers, _ = identity_boundary
    common = {"type": "source_read", "kind": "file", "uri": "file:///secret", "content_hash": "a" * 64}
    canonical = post_events(client, headers, [{**common, "id": "original", "conf": ["private"]}])[0]
    created = post_events(client, headers, [
        {"type": "ensure_session"},
        {**common, "id": "alias", "conf": []},
        {"type": "session_read", "node_id": "alias"},
        {"type": "memory", "id": "derived", "text": "still private", "derived_from": ["alias"]},
        {"type": "action", "id": "acted", "tool": "Read", "relied_on": ["alias"]},
    ])
    assert created[0] == canonical
    assert db.ro_query(graph, "MATCH (s:Session)-[:READ]->(n:Source) RETURN n.id").result_set == [[canonical]]
    rows = db.ro_query(graph, "MATCH (n:Node)-[:DERIVED_FROM]->(s:Source) RETURN n.id,s.id,n.conf_eff").result_set
    assert sorted(rows) == [["acted", canonical, ["private"]], ["derived", canonical, ["private"]]]


def test_identity_lookup_is_graph_local(identity_boundary):
    db, _, graph, client, headers, registry = identity_boundary
    other = "ti" + uuid.uuid4().hex[:10]
    other_graph = graph_name(other)
    credential = registry.create_tenant(other)
    ensure_schema(db, other_graph)
    try:
        common = {"type": "source", "kind": "file", "uri": "file:///same", "content_hash": "a" * 64}
        first = post_events(client, headers, [{**common, "conf": ["private"]}])[0]
        revoke(db, graph, registry.resolve(headers["Authorization"].split()[1]).tenant_id, root_id=first)
        second = post_events(client, {"Authorization": "Bearer " + credential.token}, [common])[0]
        assert db.ro_query(other_graph, "MATCH (s:Source) RETURN s.id,s.status,s.conf_eff").result_set == [[second, "ok", []]]
        assert db.ro_query(graph, "MATCH (s:Source) RETURN s.id,s.status,s.conf_eff").result_set == [[first, "revoked", ["private"]]]
    finally:
        db.select(other_graph).delete()
        db.query(registry.gname, "MATCH (t:Tenant {id:$id}) DELETE t", {"id": other})
