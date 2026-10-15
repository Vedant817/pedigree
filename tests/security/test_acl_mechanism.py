"""Per-tenant DB ACL users (docs/05 AT2.3, pack `13_acl_tenant_isolation.py` pattern).

This test proves the mechanism works on the pinned FalkorDB v4.22.1: a user scoped to
`~ped:<tenant>` and `~ped:<tenant>:wi:*` can work in its own namespace and is denied every
other graph, including copying into a foreign namespace.

Skipped unless `PEDIGREE_DB_ACL_SECRET` is set (the ACL user password is deployment
configuration, never committed). Wiring these users into the running service is a documented
residual - see `docs/KNOWN_ISSUES.md` - and the API-level isolation matrix in
`tests/integration/test_isolation_concurrency.py` covers what the service enforces today.
"""
from __future__ import annotations

import os
import uuid

import pytest
from falkordb import FalkorDB

from pedigree.config import graph_name

SECRET = os.getenv("PEDIGREE_DB_ACL_SECRET", "")
#: The ACL user's password is the deployment secret, set on the user itself (never committed);
#: `+graph.list` is deliberately absent - GRAPH.LIST exposes every graph name (pack note).
USER_COMMANDS = [
    "on", f">{SECRET}", "resetkeys", "-@all", "+info", "+ping",
    "+graph.query", "+graph.ro_query", "+graph.explain", "+graph.delete", "+graph.copy",
    "+graph.constraint",
]


@pytest.fixture(scope="module")
def admin():
    from pedigree.config import get_settings

    s = get_settings()
    return FalkorDB(host=s.falkor_host, port=s.falkor_port)


@pytest.mark.skipif(not SECRET, reason="PEDIGREE_DB_ACL_SECRET not set (deployment secret)")
def test_acl_user_cannot_cross_tenant_namespaces(admin):
    from pedigree.config import get_settings

    s = get_settings()
    a = "acl" + uuid.uuid4().hex[:8]
    b = "acl" + uuid.uuid4().hex[:8]
    ga, gb = graph_name(a), graph_name(b)
    try:
        admin.select_graph(ga).query("MERGE (:Node {id:'x'})")
        admin.select_graph(gb).query("MERGE (:Node {id:'x'})")
        for tenant, graph in ((a, ga), (b, gb)):
            admin.connection.execute_command(
                "ACL", "SETUSER", f"t_{tenant}", *USER_COMMANDS,
                f"~ped:{tenant}", f"~ped:{tenant}:wi:*")
        scoped = FalkorDB(host=s.falkor_host, port=s.falkor_port,
                          username=f"t_{a}", password=SECRET)
        assert scoped.select_graph(ga).query("RETURN 1").result_set == [[1]]
        for other in (gb, "ped:zzz", "pedigree:registry"):
            with pytest.raises(Exception) as excinfo:
                scoped.select_graph(other).ro_query("MATCH (n) RETURN count(n)")
            assert "permission" in str(excinfo.value).lower() or "no permissions" in str(excinfo.value).lower()
        scoped.select_graph(ga).copy(f"{ga}:wi:1")
        scoped.select_graph(f"{ga}:wi:1").delete()
        with pytest.raises(Exception):
            scoped.select_graph(ga).copy(f"{gb}:evil")
    finally:
        for graph in (ga, gb, f"{ga}:wi:1"):
            try:
                admin.select_graph(graph).delete()
            except Exception:  # noqa: BLE001 - already gone / forbidden for the admin user
                pass
        for user in (f"t_{a}", f"t_{b}"):
            try:
                admin.connection.execute_command("ACL", "DELUSER", user)
            except Exception:  # noqa: BLE001
                pass
