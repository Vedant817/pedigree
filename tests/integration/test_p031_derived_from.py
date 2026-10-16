"""P-031 (B4): derived_from parents are restricted to Source/Memory/Action (FIX_PROMPT B4)."""
from __future__ import annotations

import uuid

import pytest

from pedigree.api.registry import TenantRegistry
from pedigree.config import graph_name
from pedigree.db.client import Db
from pedigree.engine.ingest import record_source, remember
from pedigree.errors import InvalidArgument


def _tenant(db):
    registry = TenantRegistry(db)
    tid = "p031" + uuid.uuid4().hex[:8]
    registry.create_tenant(tid)
    return registry, tid


def _drop(db, registry, tid):
    try:
        db.select(graph_name(tid)).delete()
    except Exception:  # noqa: BLE001
        pass
    db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tid})


def test_derived_from_rejects_session_parent():
    db = Db()
    registry, tid = _tenant(db)
    gname = graph_name(tid)
    session_id = "sesh01"
    db.query(gname, "CREATE (:Node:Session {id:$id, tenant:$t, status:'ok', runtime:'x'})",
             {"id": session_id, "t": tid}, op="test.seed")
    try:
        with pytest.raises(InvalidArgument) as ei:
            remember(db, gname, tid, text="x", derived_from=[session_id])
        assert "Source, Memory, or Action" in str(ei.value)
    finally:
        _drop(db, registry, tid)


def test_derived_from_accepts_source_parent():
    db = Db()
    registry, tid = _tenant(db)
    gname = graph_name(tid)
    try:
        src = record_source(db, gname, tid, kind="web", uri="https://t/x", title="x", integrity="trusted")
        m = remember(db, gname, tid, text="x", derived_from=[src.id])
        assert m.id is not None
    finally:
        _drop(db, registry, tid)
