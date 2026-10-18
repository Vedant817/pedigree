# Tenant database ACL: local builder evidence

Scope: authenticated REST/MCP engine operations and startup recovery use scoped
database credentials. This is builder verification, pending independent security
review and hosted/TestSprite acceptance. No graph-mutating command touched the
existing database; this run used a fresh dedicated container on port 6382.

Runtime: Python 3.12.15, Docker 29.8.2, FalkorDB image v4.22.1; `MODULE LIST`
returned graph module version 42201. Commands selected this worktree's `src`
through PYTHONPATH and the existing development Python virtualenv through Make's
PY override.

- Initial new regression run: missing `Db.for_tenant`/namespace helper produced
  4 failures; fixture injection teardown also errored and was corrected before
  final verification. No test assertion was weakened.
- Focused pytest run over `test_tenant_db_service.py`, `test_api.py`,
  `test_mcp.py`, `test_whatif.py`, `test_revoke_resume.py`:
  `31 passed in 7.92s` (exit 0).
- `make check`: Ruff PASS; `880 passed, 1 skipped, 6 deselected, 1 xfailed in
  183.62s`; tracked secret scan PASS; numbers PASS (4 files, 70 allowed values);
  README PASS (exit 0).
- `make check-perf`: `4 passed, 884 deselected in 6.16s` (exit 0).
- `git diff --check`: exit 0.

Direct attacks using the service-selected Redis client denied foreign graph reads,
foreign copy destinations, registry reads, graph enumeration, ACL enumeration and
foreign quota key writes. A namespace property test checks exact/prefix boundaries.
Normal schema creation, quota writes, what-if, revoke and reinstate succeeded.
REST/MCP engine operations passed with the administrator graph selector instrumented
to reject every tenant graph. Startup recovery receives scoped connections.
Injected ACL provisioning failure returned HTTP 503 without administrative fallback.
Deleting a service tenant's ACL identity was repaired on the next admission.

`testsprite --version` returned 0.14.0 and `testsprite auth status` confirmed configured
credentials. No TestSprite run is claimed: this worktree has not been pushed/deployed,
so no deployed backend target contains this patch. PR/preview/TestSprite verification
belongs to the integration/release gate. Local passing tests do not replace it.

Deployment requirements: production ACL secret at least 32 characters, same across
all processes; private authenticated DB networking; explicit ACL-disabled mode only
where its weaker API-only isolation is accepted. Development's process-local secret
is not suitable for multiple independently launched services sharing one database.
