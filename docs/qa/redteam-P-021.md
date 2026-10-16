# P-021 independent red-team: PASS for exercised boundaries

2026-10-17, 01:58 IST. Reviewer: delegated `p021_redteam`, independent of the
implementation. Scope: consult 011 / ADR-012 strict validation, safe diagnostics
and request-byte admission, including P-015 and P-014 regression attacks. This
reviewer edited only `tests/security/test_p021_attacks.py` and this report.

## Actual commands and output

```text
.venv/Scripts/python.exe -m pytest tests/security/test_p021_attacks.py -q -s --tb=short
.............................[fixture-ownership] PASS: session sentinel graph and registry unchanged
29 passed in 17.48s
```

```text
.venv/Scripts/python.exe -m ruff check tests/security/test_p021_attacks.py
All checks passed!
```

The first iteration returned `1 failed, 21 passed in 14.22s`. The failed HTTP
probe omitted MCP's required Accept types and received SDK 406 before the desired
malformed-envelope check. With `Accept: application/json, text/event-stream`, the
focused group passed (`1 passed, 21 deselected in 2.60s`). This was a transport
prerequisite correction, not a demonstrated product repair. Seven added lone
Unicode-surrogate cases passed (`7 passed, 22 deselected in 4.75s`), then the full
29-case run above passed. No independently reproduced product defect remained.
The surrogate probes are observed coverage, not evidence of a new source fix.

## Attacks and observed results

1. Real REST events with a valid first Source followed by malformed raw tails:
   list/dict discriminators, list source-kind, dict integrity/conf, conflicting
   scalar/container aliases, a dict dependency item, hidden `by=human`, vertical
   tab in URI, and list session ID. The agent also supplies the valid deployment
   admin header. Each returns typed 422 or 403, never a 500; exact graph node and
   edge snapshots stay unchanged. Caller canary values do not appear in errors.
2. Real REST JSON with escaped lone surrogate `\ud800` in URI, title, Memory text,
   Action summary and artifact, each after a valid prefix Source: all return
   422 `invalid_argument`, exact snapshots unchanged. Direct installed SDK calls
   with a surrogate URI/text also return `invalid_argument` before writes.
3. Agent plus deployment admin header attempts trusted Source classification
   through legacy `kind=human`, `type=source_read/source_kind=human`, and
   `kind=source.create/integrity=trusted` aliases: all 403, graph empty. Two valid
   agent Sources fill the owned cap of two; another events Source receives 429
   `quota_exceeded`, and another MCP Source receives `quota_exceeded`. Both leave
   the exact full graph unchanged. This verifies a real successful journey as
   well as the role/quota denials.
4. Forced SDK schema, auth and engine faults contain both a private outer
   exception value and chained cause value. Each direct installed SDK call
   returns `internal` and a generated 32-character correlation ID. Neither
   response nor captured logs contain those values or the minted bearer. Error
   records have no raw `exc_info`. Exact graph snapshots remain unchanged.
5. Synthetic ASGI streaming handlers raise after response start, both before and
   after the final body. Exactly one status is sent; unfinished bodies receive
   only a terminating empty body. No second response or exception escapes. Logs
   contain the outer RuntimeError class, not the ValueError cause or either
   exception value. A hostile incoming correlation header is not reflected.
6. Actual TCP Uvicorn requests use chunked framing, splitting valid JSON across
   three chunks, at exactly 262144 bytes and one byte over. `/v1/events` accepts
   the exact-cap empty batch (200) and rejects overflow with 413 `too_large`.
   Mounted `/mcp` parses exact-cap `{}` to its safe malformed-protocol 400 and
   rejects overflow with 413. No graph changes occur. These are real wire
   requests, distinct from synthetic false Content-Length/disconnect coverage.
7. Actual TCP MCP server with a configured local default agent credential:
   malformed dict/list IDs, bad params and boolean method receive safe 400
   JSON-RPC errors with `id=null`; malformed private values are not reflected.
   A successful SDK initialization then reaches tool calls: missing HTTP auth
   cannot inherit the local default (`unauthorized`); an empty authoritative
   header cannot fall back to an explicit operator argument (`unauthorized`);
   agent plus deployment admin header cannot create human Sources (`forbidden`);
   unknown tool fields with canary values return `invalid_argument`. No graph
   writes or canary log leakage occur.
8. Actual CLI stdio subprocess initializes the installed SDK, receives malformed
   JSON then a malformed list request ID, and returns safe JSON-RPC -32600 with
   `id=null` after each. A malformed health argument returns `invalid_argument`.
   A valid health call then succeeds on the same stream. Captured stderr and
   rendered replies contain no private canary.

## Evidence limits and ownership

The graph probes use local pinned FalkorDB module 42201 through the real Db
fixture; its unrelated session sentinel graph and registry were unchanged. Each
review fixture deletes only its exact newly created tenant registry row and graph.
No historical tenants, graphs or coordination keys were swept. This does not
establish that previous runs left no data behind.

Fault injection and after-response-start behavior are deliberately labeled above;
they do not claim naturally occurring engine/database failures. The SDK transport
tests prove local installed HTTP/stdio behavior, not an installed agent runtime,
hosted deployment, concurrent load guarantee, production readiness or all Unicode
and protocol cases. Whole-repository checks and dogfood belong to the parent run.
No paid provider was invoked and no bearer value is recorded here.
