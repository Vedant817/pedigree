"""Shared test fixtures. Integration tests run against a REAL FalkorDB (no mocks)."""

from __future__ import annotations

import uuid

import pytest

from pedigree.config import graph_name
from pedigree.db.client import Db
from pedigree.db.schema import ensure_schema


@pytest.fixture(scope="session")
def db() -> Db:
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
    return d


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
