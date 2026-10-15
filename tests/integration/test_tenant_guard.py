"""QA finding 2026-10-15 (medium): engine entry points accepted any tenant string and wrote
it into the graph. Every entry point now validates the tenant before touching the DB, and a
rejected call must leave the graph completely unchanged (no partial writes)."""

from __future__ import annotations

import pytest

from pedigree.db.schema import node_count
from pedigree.engine.ingest import record_action, record_source, remember
from pedigree.engine.revoke import reinstate, revoke
from pedigree.errors import InvalidArgument

BAD_TENANTS = ["ab", "ABCD", "a b", "a_b", "abc:x", "", "x" * 25, "not a valid tenant!"]


@pytest.mark.parametrize("bad", BAD_TENANTS)
def test_ingest_rejects_bad_tenant_without_writing(fresh_graph, bad):
    db, _tenant, gname = fresh_graph
    before = node_count(db, gname)

    with pytest.raises(InvalidArgument):
        record_source(db, gname, bad, kind="web", id="s1")
    with pytest.raises(InvalidArgument):
        remember(db, gname, bad, text="x", id="m1")
    with pytest.raises(InvalidArgument):
        record_action(db, gname, bad, tool="git push", id="a1")

    assert node_count(db, gname) == before == 0


@pytest.mark.parametrize("bad", ["ab", "ABCD", "abc:x"])
def test_revoke_and_reinstate_reject_bad_tenant(fresh_graph, bad):
    db, tenant, gname = fresh_graph
    record_source(db, gname, tenant, kind="web", id="s1")
    before = node_count(db, gname)

    with pytest.raises(InvalidArgument):
        revoke(db, gname, bad, root_id="s1", reason="x")
    with pytest.raises(InvalidArgument):
        reinstate(db, gname, bad, root_id="s1")

    assert node_count(db, gname) == before  # nothing revoked, no Revocation row
