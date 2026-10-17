# P-020 independent red-team: PASS for exercised boundaries

2026-10-17. Reviewer: delegated `p020_redteam`, independent of the implementation.
Scope: consult 012 / ADR-013 live indexed authority, bounded per-instance admission,
REST and mounted MCP sharing, failed-auth peer scope, and P-015/P-021 regressions.
Base HEAD observed `c724668`; P-020 source was an uncommitted working-tree patch.
Reviewer edited only `tests/security/test_p020_attacks.py` and this report.

## Actual commands and output

```text
.venv/Scripts/python.exe -m pytest tests/security/test_p020_attacks.py tests/security/test_p020_review.py::test_shipped_cli_stdio_backoff_is_server_local_and_blocks_valid_default -q -s --tb=short
.............[fixture-ownership] PASS: session sentinel graph and registry unchanged
13 passed in 4.25s
```

Twelve independently authored attack tests plus the independent QA reviewer's actual
CLI stdio test passed. The latter was run unchanged as additional transport evidence.

```text
.venv/Scripts/python.exe -m ruff check tests/security/test_p020_attacks.py
All checks passed!
```

The initial run was `1 failed, 9 passed in 3.24s`: this reviewer's fixture started
the same SDK session manager twice (TestClient lifespan then Uvicorn lifespan).
The installed SDK correctly rejected the second startup. A fresh TCP app sharing
the same real registry and limiter fixed the test setup; no product change followed.
The corrected ten-test run was `10 passed in 2.91s`, before two additional attacks.

## Attacks and observed outcomes

1. **Indexed live authority and corrupt registry candidates.** A dedicated owned
   registry graph resolves agent/operator credentials, immediately rejects a rotated
   operator credential and a revoked tenant, permits a nullable-slot legacy tenant
   whose ID begins `o_` only as agent, and rejects a mismatched operator prefix and
   duplicate digest candidates. Observed digest EXPLAIN uses `Node By Index Scan`
   without label scans; observed resolve/management calls never use the tenant-list
   query. This is local pinned-module execution-plan evidence, not a production
   latency or mathematical constant-time claim.
2. **Concurrent authentication samples and key saturation.** Forty-eight concurrent
   failed-auth reservations admit exactly three samples. A second tenant key admits
   exactly two writes. Forty fresh peer and tenant names all fail at the two-key
   capacity; neither exhausted key gets reset or evicted. State stays exactly two
   keys with deques of lengths two and three. At injected time 60 seconds, expired
   keys prune and a new tenant can be admitted. This directly exercises real limiter
   locking and state; injected time is deterministic algorithm evidence.
3. **Atomic dual-budget reservations.** For both real and dry-run revocation,
   thirty concurrent opposite-mode reinstatement reservations all reject after the
   destructive bucket fills. They neither create nor spend the other read/write
   bucket. One subsequent ordinary operation uses its still-complete allowance.
4. **Route/tool omission attack.** Fill a real shared tenant read budget, then
   exercise stats, graph, UI graph view, audit, blame, impact, invariants and artifact
   lookup REST routes and every MCP graph read tool: all return rate-limited. Fill
   a write budget, then exercise Source/Memory/Action/corroboration/session/session
   read/events/recorded gate/what-if/revoke/reinstate REST routes and every corresponding
   MCP writer: all rate-limit, and the graph retains exactly its one admitted node.
   Cross-role use does not yield another allowance. Public health/static endpoints
   have no tenant identity; health remains callable intentionally. Deployment-admin
   successes are outside tenant budgets; their failures share peer backoff.
5. **Real concurrent cross-role writes.** Twenty-four installed-SDK Source calls
   alternate agent/operator tokens against the real DB and one three-write limiter:
   exactly three succeed, twenty-one return `rate_limited`, and exactly three graph
   nodes persist. Nested quota/engine work does not double-charge admission.
6. **Failed auth, NAT blocking and prelookup threshold.** Missing/malformed headers
   and an invalid token yield the first three 401 outcomes; only the invalid-token
   request reaches registry lookup. Five subsequent valid-token requests with varied
   forwarding headers receive 429 before another lookup. Injected expiry restores
   the valid request. Shared-IP valid-user denial is the chosen availability tradeoff,
   not isolation by caller-provided headers.
7. **Actual TCP mounted MCP and REST.** A Uvicorn listener with a fresh application
   accepts one operator MCP Source over the installed streamable-HTTP client; the
   agent REST Source receives 429 from the same write budget. Two invalid MCP
   authentications with spoofed X-Forwarded-For exhaust the actual `127.0.0.1` peer;
   a valid REST operator with both Forwarded and X-Forwarded-For receives 429. No
   spoofed addresses become limiter keys. This is local wire evidence, not hosted
   proxy configuration proof.
8. **Shipped launch and stdio scope.** Intercepted Uvicorn launch arguments confirm
   REST, MCP streamable HTTP and MCP SSE explicitly set `proxy_headers=False`.
   This launch inspection complements the wire spoof test; it is not a deployed
   reverse-proxy test. Direct installed-SDK calls with different forged tenant hints
   share `local:stdio`; after two failures even the valid default/operator token is
   rate-limited. Separately, the unchanged QA test launches the actual shipped CLI
   stdio subprocess and verifies ten failures block a valid configured default.
9. **Permission precedence and safe errors.** An exhausted write budget does not
   turn agent revoke or trusted Source attempts into admitted work: both still
   return forbidden. A valid deployment-admin header does not upgrade the agent.
   An unknown MCP argument returns `invalid_argument` without its private canary;
   checked errors do not reflect the minted bearer.

## Security policy review and limits

Read current `SECURITY.md` alongside the implementation. Its live stored-authority,
legacy-agent, per-instance/reset/multi-worker, trustworthy peer and non-distributed
claims agree with the exercised contract. Its quota mutex/no-fencing, privileged DB,
fail-open hook, incomplete installed-runtime and metrics qualifications do not hide
these rate-limit threats. No contradictory security claim or blanket exclusion was
identified. The policy honestly leaves the private disclosure contact as a release
TODO, rather than claiming an unmonitored address exists.

All tests use real pinned FalkorDB fixtures. The authority corruption graph is
separate and deleted by exact name; service registry cleanup deletes only the exact
owned tenant ID. The session ownership sentinel remained unchanged. No global graph,
registry or key cleanup ran; no credential or digest was printed.

No independently reproduced unresolved P-020 bypass remained. Limits intentionally
remain per-instance and in-memory; restarts and extra workers multiply allowance.
Already-in-flight concurrent authentication work can exceed the failed-auth lookup
threshold before outcomes are recorded. The tests do not claim a hard DB-work bound,
production throughput, hosted proxy trust, distributed throttling, or full Phase C
completion. Full check, dogfood and clean-clone verification remain parent-owned.
