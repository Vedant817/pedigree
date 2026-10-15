# tech/ - verified FalkorDB runtime kit (no Docker, no binaries shipped)
- `bash setup.sh` -> creates `.venv`, installs `falkordblite==0.10.0 falkordb==1.8.0 mcp>=2,<3` (the wheel provides `redis-server`), downloads the pinned FalkorDB **v4.22.1** `.so` via `fetch-falkordb.sh` (51 MB, not in this pack) and `chmod +x` it.
- `PORT=6379 DATA_DIR=$PWD/data ./start-falkordb.sh &` starts the server with the mandatory limits. Verify: `.venv/bin/redis-cli -p 6379 MODULE LIST` shows `graph ... ver 42201`.
- Prove it: `FALKOR_PORT=6379 .venv/bin/python examples/py/12_pedigree_core.py` (Pedigree core prototype + race test) and `13_acl_tenant_isolation.py` (ACL isolation).
- Docs: `TECH_REFERENCE.md` (verification table, benchmarks, integrations), `GOTCHAS.md` (traps incl. section 16-20 added for Pedigree), `bench/` raw outputs (4.18.3 and 4.22.1), `examples/` runnable scripts (Python, Node, MCP python+ts).
- Not included on purpose: `.venv`, `bin/*.so`, `data/`, `browser-src/`, `docs_cache/` (offline copies of official docs: fetch from https://docs.falkordb.com when needed).
- Wheel's bundled `falkordb.so` is 4.18.3 (used only if the pinned file is missing; `DUMP/RESTORE` crashes there).
