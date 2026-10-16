"""P-011 kill-process driver: run a revoke, hard-exit 7 after first final-write chunk.

Usage: python _crash_driver_revoke.py <tenant> <root_id>
Graph+tenant must already exist (created by the parent test).
"""
from __future__ import annotations

import os
import sys

import pedigree.engine.revoke as revoke_mod
from pedigree.config import graph_name
from pedigree.db.client import Db
from pedigree.db.client import chunks as real_chunks
from pedigree.engine.revoke import revoke


def main() -> int:
    tenant, root = sys.argv[1], sys.argv[2]
    db = Db()
    gname = graph_name(tenant)
    orig = db.query
    state = {"writes": 0}

    def q(g, query, params=None, **kw):
        if kw.get("op") == "revoke.write":
            state["writes"] += 1
            r = orig(g, query, params, **kw)
            if state["writes"] == 1:
                os._exit(7)
            return r
        return orig(g, query, params, **kw)

    db.query = q
    revoke_mod.chunks = lambda xs: real_chunks(xs, 2)
    revoke(db, gname, tenant, root_id=root, reason="kill-driver")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
