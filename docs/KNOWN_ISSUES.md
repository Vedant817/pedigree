# Known issues and limits

Open items are tracked here (with a link to the failing test or the evidence). A feature
that cannot be finished goes here rather than being silently dropped.

| # | Date | Item | Severity | Status |
|---|---|---|---|---|
| 1 | 2026-10-15 | Development host is Windows; FalkorDB 4.22.1 runs via the pinned Docker image instead of the Linux `.so`+wheel path. The Linux/no-Docker path is shipped (`scripts/*.sh`) and is exercised by the production `Dockerfile`. | low | accepted (ADR-001) |
| 2 | 2026-10-15 | The user's home directory `C:\Users\vedan` is itself a git repository (no commits). The Pedigree repo is a separate repository nested inside it; git commands inside `pedigree/` use the local `.git`. | informational | noted |
| 3 | 2026-10-15 | FalkorDB Cloud Free tier has no TLS and no persistence; if used for the hosted demo it will hold synthetic demo data only. | low | documented |
| 4 | 2026-10-15 | `scripts/start-falkordb.sh` / `fetch-falkordb.sh` (Linux no-Docker path) are written from the docs but NOT yet executed on a real Linux host; first execution will be during the F-16 Docker build, which uses the same mechanism. | medium | open, tracked (F-16) |
| 5 | 2026-10-15 | `make demo` now seeds synthetic S1/S8 idempotently, preserves changed lifecycle/support authority, and keeps credentials in ignored scratch. | low | resolved, F-10 |
| 6 | 2026-10-15 | `docs/WALKTHROUGH.md` is referenced by the README doc map but is written in Phase 4. | informational | planned (F-23) |
| 7 | 2026-10-15 | Static-Cypher lint is a guard-rail, not a proof: it cannot see strings assembled through variables or external data. Coverage now includes f-strings, `.format`/`.replace`/`.join` on literals, concatenation and `%`. Manual review + parameterised query constants remain the primary control. | low | documented |
| 8 | 2026-10-15 | `:Revocation` nodes carry `state` (running/done) instead of `status`; the missing-status invariant explicitly exempts them. Deviation from docs/01 §5 recorded in ADR-006. | low | accepted (ADR-006) |
| 9 | 2026-10-15 | `POST /v1/events` applies operations in order and aborts on the first typed error, so a failing batch leaves the earlier events applied (no cross-event atomicity). Acceptable for the idempotent capture channel; documented in `docs/qa/F-07.md`. | low | documented |
| 10 | 2026-10-15 | `BodySizeMiddleware` compares against a literal `256 * 1024` instead of `LIMITS["body_bytes"]` (identical value). | informational | cosmetic |
| 11 | 2026-10-15 | Human/scanner corroboration remains an explicit caller assertion. Defaults are agent everywhere, but a bearer-token holder can explicitly claim a trusted role. | high | open, F-13 authority separation |
| 12 | 2026-10-15 | Claude hooks have synthetic contract and real localhost HTTP subprocess proof, but no installed-runtime execution. Web/tool-description sources and shell file I/O are not captured. Repeated unmatched file reads create separate Source ids, so revoking one id does not identify future identical reads. | high | open, F-07/F-08 capture fidelity and source identity |
| 13 | 2026-10-15 | Runtime registry uses ped:registry while unused REGISTRY_GRAPH and original spec say pedigree:registry. Reserved tenant id prevents collision; deployment/ACL docs must use the actual name until migrated. | medium | open, F-13 consistency |
| 14 | 2026-10-15 | Shell classification is a regex heuristic, not a sandbox. Hook network/malformed-payload failures are fail-open. | medium | documented, F-11 |
| 15 | 2026-10-15 | OpenCode free provider returned Free usage exceeded, subscribe to Go during an isolated synthetic session. Plugin startup events are real; tool before/after events were never emitted. | medium | F-08 blocked; see opencode-spike.md |
