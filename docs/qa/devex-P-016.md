# Devex review — P-016 (MCP invocation fix + `/mcp` mount)

- **Reviewer:** `devex-reviewer` subagent (persona: first-time developer connecting an MCP client).
- **Frozen commit:** `561b7e2` (P-016 fix; `make check` 403 passed, 1 skipped, 3 deselected, 1 xfailed).
- **Environment:** Windows; `.venv/Scripts/python.exe`; FalkorDB `falkordb/falkordb:v4.22.1` running.
- **Provenance note:** the reviewer hit its step limit before writing this file; the evidence below is
  transcribed from its session summary. Orchestrator completed the leftover cleanup (tenant
  `dx169683e3` graph + registry row deleted, serve PID stopped, temp project removed) after receipt.

## What was executed (real commands, as reported)

| Step | Result |
|---|---|
| `python -m pedigree.cli --help` / `mcp --help` | only `--transport/--host/--port`; no mention of the tenant env vars |
| `make demo` | 0.8 s, seeds demo S1+S6+S8, prints only the credential **file path** (`scratch/demo-demo.json`) — contradicts README "prints it" / "paste the token `make demo` printed" |
| `python -m pedigree.cli db status` | reachable, module ver 42201 (OK) |
| `python -m pedigree.cli serve` (README path) | up on 127.0.0.1:8000; log shows "StreamableHTTP session manager started"; `/healthz` 200, `/readyz` 200, `/` 200 (UI), `/docs` 200 |
| `GET /mcp` (browser) | 400 "Missing session ID" (mount works; previously 404) |
| SDK client (`mcp` 2.3.0, streamable HTTP @ documented URL) | initialize OK (`server_info.name=pedigree`, protocol `2025-11-25`), 13 tools; `pedigree_record_source` with token **argument** → `ok` (`src_0361…`, `low_integrity:true`, warning `untrusted_source`); `pedigree_blame` → ok; cross-tenant blame → `not_in_graph` |
| stdio client (`python -m pedigree.cli mcp --transport stdio`) | no env vars: initialize/tools/`pedigree_health` work, tenant tools → `{"ok":false,"error":{"code":"unauthorized","message":null}}`; with `PEDIGREE_MCP_TENANT`/`PEDIGREE_MCP_TOKEN` works without token arg |
| `opencode mcp list` (opencode 1.19.0, repo config) | `○ pedigree disabled — http://127.0.0.1:8000/mcp` (matches `enabled:false`) |
| OpenCode temp project, `enabled:true`, `PEDIGREE_TOKEN` unset | `✓ pedigree connected` — transport connects; empty bearer is NOT validated |
| REST error-quality comparison | bad bearer → `{"code":"unauthorized","message":"invalid token"}`; admin no header → `"admin token required"`; malformed JSON body → raw FastAPI `detail:[…]` shape, no error envelope/correlation id |

## Findings (ranked)

1. **BLOCKER — no documented working auth path for MCP tool calls.** Every tenant tool needs a
   `token` **argument**, but README/`opencode.json` imply the `Authorization: Bearer {env:PEDIGREE_TOKEN}`
   header does it (header not consumed; P-015 pending). Header-only call →
   `{"ok":false,"error":{"code":"unauthorized","message":null}}`.
   *Fix (now):* README MCP block states the interim reality ("pass `token=<ped_…>` as a tool argument").
   *Fix (P-015):* consume the agent token from the header; roles.
2. **MAJOR — error message is literally `null`** for missing/wrong token and tenant-id-only calls;
   `pedigree_check_action` returns no `message` at all. Non-actionable dead end.
   *Fix (P-016 follow-up):* `mcp_server.py` returns actionable messages.
3. **MAJOR — README's `make demo` claim is false** (writes but does not print the token; re-runs point
   to "the previously issued token in the UI" which the UI never shows); `PEDIGREE_TOKEN` for
   `opencode.json` is never explained. *Queued:* P-002 (README standard) / P-027 (demo), noted here.
4. **Minor:** stdio auth undocumented; cheat-sheet command `python -m pedigree.mcp_server --stdio`
   (`docs/09-TECH-CHEATSHEET.md:66`) is dead (exits immediately, no output) — should be
   `python -m pedigree.cli mcp --transport stdio`; README tool list omits `pedigree_whatif` /
   `pedigree_audit_sources`; browser `GET /mcp` 400 is unhelpful but correct; UI legend names the five
   statuses without defining them; depth slider has no hint; malformed-body errors bypass the typed
   error envelope (P-021 scope).

## Boundary / not verified

- No end-to-end agent tool call was executed through `opencode run` (no model invocation) — only the
  config/connection layer.
- "Server not running" / "wrong port" client-error cases were planned last and not captured.
- Cleanup of the reviewer's artifacts was completed by the orchestrator after this report was received.

## Verdict

**3-minute onboarding: NOT achievable at this commit.** Two changes get it there: the README MCP
auth-reality fix (this item's follow-up) and actionable MCP error messages; the full header/role story
lands with P-015.
