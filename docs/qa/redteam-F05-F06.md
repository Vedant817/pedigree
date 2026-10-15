# Red-team report F-05 / F-06

## Fixed findings
- BodySizeMiddleware accepted malformed `Content-Length` and crashed (fixed in `app.py`).
- `TenantRegistry` allowed reserved `tenant_id="registry"`, colliding with registry graph (fixed in `registry.py`).
- MCP allowed access to a tenant with only `tenant_id` and no token in shared-server mode (fixed `_resolve`).
- MCP write tools did not enforce `node_cap` (quota checks added).
- REST `SourceCreate.integrity` allowed only `low/high` while engine requires `trusted/untrusted` (fixed schema Literal).
- CLI docs claimed `pedigree mcp`, but the command was missing (patched into CLI).

## Security tests
- `tests/security/test_security_F05.py`: 5 tests pass.
- `tests/security/test_security_F06.py`: 5 tests pass.

## Remaining follow-up
- Consider dedicated reserved-tenant validation rather than InvalidArgument if a different HTTP code is preferred.
- Deep nesting/spool/hook transformations handled in later features F-07+.

Verdict: PASS (hardened, no open critical blocking issues).