"""Shared test fixtures. Integration tests run against a REAL FalkorDB (no mocks)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest

from pedigree.config import graph_name
from pedigree.db.client import Db
from pedigree.db.schema import ensure_schema


@pytest.fixture(scope="session")
def db() -> Iterator[Db]:
    d = Db()
    if not d.ping():
        pytest.fail(
            "FalkorDB is not reachable - run `make start-db` first "
            "(Docker image falkordb/falkordb:v4.22.1, or scripts/start-falkordb.sh on Linux).",
            pytrace=False,
        )
    ver = d.module_version()
    if ver != 42201:
        pytest.fail(f"FalkorDB module version is {ver}, expected 42201 (v4.22.1 pinned).", pytrace=False)
    # A session-owned, unrelated tenant detects destructive cleanup anywhere in a
    # DB-using test run. Unit-only runs never request this fixture or touch the DB.
    from pedigree.api.registry import TenantRegistry
    from pedigree.engine.ingest import record_source

    tenant = "qsession" + uuid.uuid4().hex[:12]
    graph = graph_name(tenant)
    registry = TenantRegistry(d)
    registry.create_tenant(tenant)  # discard one-time credential immediately
    try:
        ensure_schema(d, graph)
        record_source(d, graph, tenant, id="ownership_sentinel", kind="web",
                      uri="local-session-ownership-guard")
        record = registry.get_record(tenant)
        nodes = d.ro_query(graph, "MATCH(n) RETURN labels(n),properties(n)").result_set
        edges = d.ro_query(graph, "MATCH(a)-[r]->(b) RETURN a.id,type(r),b.id,properties(r)").result_set
        yield d
        assert graph in d.list_graphs(), "session ownership sentinel graph was deleted"
        assert registry.get_record(tenant) == record, "session ownership sentinel registry changed"
        assert d.ro_query(graph, "MATCH(n) RETURN labels(n),properties(n)").result_set == nodes
        assert d.ro_query(graph, "MATCH(a)-[r]->(b) RETURN a.id,type(r),b.id,properties(r)").result_set == edges
        print("[fixture-ownership] PASS: session sentinel graph and registry unchanged")
    finally:
        # Never enumerate registry tenants for cleanup; this fixture owns one ID.
        try:
            if graph in d.list_graphs():
                d.select(graph).delete()
        finally:
            d.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id":tenant})


def drop_graph(db: Db, gname: str) -> None:
    try:
        db.select(gname).delete()
    except Exception:  # noqa: BLE001 - missing graph raises
        pass


@pytest.fixture()
def fresh_graph(db: Db):
    """A throwaway tenant graph with schema applied; deleted afterwards."""
    tenant = "t" + uuid.uuid4().hex[:10]
    gname = graph_name(tenant)
    drop_graph(db, gname)
    ensure_schema(db, gname)
    try:
        yield db, tenant, gname
    finally:
        drop_graph(db, gname)
