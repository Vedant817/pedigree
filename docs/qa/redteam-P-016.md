# Red-team — P-016 (`/mcp` streamable-HTTP mount + MCP invocation)

- **Target:** commit `561b7e2`; local `uvicorn pedigree.api.app:create_app --factory` on 127.0.0.1:8237.
- **Attack tenants:** `rt16a03d7e792`, `rt16b03d7e792`, `rt16c03d7e792`, `rt16d4037914e` (all graphs +
  registry rows deleted and verified empty at close; server stopped).
- **Provenance note:** the `red-team` subagent hit its step limit before writing this file; the evidence
  below is transcribed from its real scratch transcripts (`%TEMP%\opencode\rt16\attack_*.utf8.txt`,
  raw files retained until OS temp cleanup; the token file `rt16-creds.json` was deleted after
  transcription). 15 cases executed in total (8 specified + 7 extras); tokens masked to first 10 chars.

## Must-fix before ship

### F-1 · HIGH · stdio ignores `PEDIGREE_MCP_TOKEN` — tenant id alone authorizes reads AND writes

Repro: `python -m pedigree.cli mcp --transport stdio` with `PEDIGREE_MCP_TENANT=rt16a03d7e792` and
`PEDIGREE_MCP_TOKEN=<garbage>` (or unset), then call tenant tools **with no `token` argument**:

```text
===== STDIO-A wrong env token, token arg OMITTED | pedigree_blame args={"tenant_id": "rt16a03d7e792", "node_id": "src_559b..."}
{"ok": true, "result": {"node": {"id": "src_559b...", "status": "ok"}, ...}}
===== STDIO-A ... | pedigree_record_source args={"tenant_id": "rt16a03d7e792", "kind": "web", "uri": "https://stdio-..."}
{"ok": true, "result": {"id": "src_c4dc60e9d22c9b9c", "status": "ok", ...}}
===== STDIO-B no token env, token arg OMITTED: env={'PEDIGREE_MCP_TENANT': 'rt16a03d7e792'}
{"ok": true, ...}   # pedigree_blame still succeeds
===== STDIO-C wrong IN-BAND token -> correctly rejected
{"ok": false, "error": {"code": "unauthorized", "message": null}}
```

- **Cause:** `mcp_server.py` `_resolve`'s tokenless branch consults only `self.default_tenant_id`;
  `default_tenant_token` is stored but never checked (grep-verified).
- **Impact:** on the stdio surface (how editors connect), knowing the semi-public tenant id grants full
  pre-P-015 tenant powers — including `revoke`/`reinstate`. A wrong-token config silently "works".
  The HTTP mount is unaffected (`default_tenant_id=None` there).
- **Fix:** tokenless branch must resolve `default_tenant_token` and require it to match
  `default_tenant_id`, else `unauthorized`; or delete the tokenless branch entirely (tool-call `token`
  arg only). Landed in the P-016 follow-up batch.
- **Test id:** `tests/security/test_p016_stdio_token.py` (wrong/missing env token + no arg → `unauthorized`).

### F-4 · MEDIUM-LOW · 256 KB body cap bypassed by `Transfer-Encoding: chunked`

```text
# Content-Length forms -> outer middleware catches them:
300KB CL -> 413 {"error":{"code":"too_large","message":"body too large"}}
5MB  CL -> 413
# chunked forms:
300KB chunked (no CL) -> reaches the tool (engine then rejected uri>512 as invalid_argument)
5MB  chunked (no CL) -> 413 "Request body too large"  (inner mcp SDK cap = 4MB; session stayed usable)
300KB chunked to REST /v1/events -> NOT 413 (reaches FastAPI; 422 downstream)
```

- **Cause:** `BodySizeMiddleware` trusts `Content-Length`; it never counts bytes read from `receive`.
- **Fix:** wrap `receive` in the middleware and count actual bytes (same pattern the mcp SDK uses);
  optionally also pass `max_request_body_size=256*1024` to `streamable_http_app()`.
- **Test id:** `tests/security/test_p016_oversize.py` (chunked 300 KB → 413 for REST and /mcp).

## Must-fix with P-015 / C4 (interim-accepted, linked)

### F-2 · MEDIUM · `/mcp` has no transport auth, no rate limit, no failed-auth throttle

- `Authorization: Bearer <valid tenant token>` is **not consumed** (header-only call → `unauthorized`;
  no `WWW-Authenticate`); the same token works on REST (`GET /v1/blame/...` → 200). An attacker holding
  only a leaked header gains nothing on `/mcp` today — the token *value* is the credential and must be
  replayed in-band.
- Unauthenticated on `/mcp`: `initialize`, `tools/list` (13 tools), `pedigree_health` (DB ping +
  module version), session create/delete.
- 40 rapid `pedigree_health` → all 200, ~5.7 ms each, no 429. 20 invalid-token calls → ~422 ms each, no
  throttle (`registry.resolve` iterates all tenants per miss — C4 scope). Cheap amplification.
- **Links:** P-015 (bearer middleware + agent/operator roles) and C4/P-020 (rate limits, O(1) auth,
  failed-auth backoff). Interim statement documented in `docs/fixes/P-016.md` + README follow-up.

### F-3 · MEDIUM · Revoked tenant token stays valid up to 30 s; MCP has a separate registry cache

- Repro: token C used once (cached), tenant revoked out-of-process, immediate call still `ok:true`;
  at +31 s → `unauthorized`. Aggravators: the cached branch ignores `status`, and the MCP server
  builds its **own** `TenantRegistry` instance (`build_mcp`), so even an in-process admin revoke would
  not invalidate the MCP cache.
- **Fix with P-015:** pass the shared registry into `build_mcp`; check `status` on cache hits;
  revisit TTL. Test id: `tests/security/test_p016_revoke_cache.py`.

### F-5 · LOW · Sessions are identity-less

- A second client reused another client's session id (`pedigree_health` 200) and DELETEd that session
  (200); the owner's next call → 404. Session ids are 128-bit random, so this is teardown/DoS, not data
  access. Bind sessions to the authenticated principal in P-015. Also: an `mcp-session-id` header is
  issued even on 400/404 responses.

## Verified clean (no finding)

No-token HTTP tool calls rejected · cross-tenant matrix (token B + tenant A on read/write/audit;
`ped:abc`-style, `:extra`, UPPER-case, prefix-subtype ids) all `unauthorized` · path smuggling
(`/mcp/../admin/tenants`, `/MCP`, `//mcp`, `/mcp/%2e%2e/healthz`, `/mcp/`, `/mcpx`, `/mcp%2f..`) all
404/307 with `/admin/tenants` still 401 · `Host: evil.example` → 421, bad `Origin` → 403 (SDK
DNS-rebinding protection auto-enabled; edge: portless `Host: 127.0.0.1`/`localhost` also 421 → P-015
should pass explicit allowed hosts) · malformed JSON-RPC / garbage / wrong content-type / bogus session
→ 400/404 JSON-RPC errors, never 500, no client-visible tracebacks · 100k-deep JSON → 400 parse error ·
Cypher-injection strings in `node_id`/`uri`/`text`/`tenant_id` treated as data, graph intact ·
`corroborate by=human|scanner` via MCP → `forbidden` · quota cap=2 vs 12 concurrent writes → exactly
2 ok / 10 `quota_exceeded`, 2 nodes (no TOCTOU observed) · no tokens or bodies in access/error logs
(one server-side SDK `ClientDisconnect` traceback on client abort mid-body — log-only).

## Verdict table

| id | severity | disposition |
|---|---|---|
| F-1 | High | **must-fix before ship** — landed in the P-016 follow-up batch |
| F-2 | Medium | interim-accepted; closed by P-015 + C4/P-020 |
| F-3 | Medium | must-fix with P-015 (shared registry, status on cache hit) |
| F-4 | Medium-low | **must-fix (small)** — byte-counting middleware; landed with P-021/input hardening |
| F-5 | Low | accepted; bind sessions to principal in P-015 |
