# Known issues and limits

Open items are tracked here (with a link to the failing test or the evidence). A feature
that cannot be finished goes here rather than being silently dropped.

| # | Date | Item | Severity | Status |
|---|---|---|---|---|
| 1 | 2026-10-15 | Development host is Windows; FalkorDB 4.22.1 runs via the pinned Docker image instead of the Linux `.so`+wheel path. The Linux/no-Docker path is shipped (`scripts/*.sh`) and is exercised by the production `Dockerfile`. | low | accepted (ADR-001) |
| 2 | 2026-10-15 | The user's home directory `C:\Users\vedan` is itself a git repository (no commits). The Pedigree repo is a separate repository nested inside it; git commands inside `pedigree/` use the local `.git`. | informational | noted |
| 3 | 2026-10-15 | FalkorDB Cloud Free tier has no TLS and no persistence; if used for the hosted demo it will hold synthetic demo data only. | low | documented |
| 4 | 2026-10-15 | `scripts/start-falkordb.sh` / `fetch-falkordb.sh` (Linux no-Docker path) are written from the docs but NOT yet executed on a real Linux host; first execution will be during the F-16 Docker build, which uses the same mechanism. | medium | open, tracked (F-16) |
| 5 | 2026-10-15 | README quick-start `make demo` exits non-zero until F-10 lands the scenario seeder; the README line is annotated. | low | open, tracked (F-10) |
| 6 | 2026-10-15 | `docs/WALKTHROUGH.md` is referenced by the README doc map but is written in Phase 4. | informational | planned (F-23) |
| 7 | 2026-10-15 | Static-Cypher lint is a guard-rail, not a proof: it cannot see strings assembled through variables or external data. Coverage now includes f-strings, `.format`/`.replace`/`.join` on literals, concatenation and `%`. Manual review + parameterised query constants remain the primary control. | low | documented |
| 8 | 2026-10-15 | `:Revocation` nodes carry `state` (running/done) instead of `status`; the missing-status invariant explicitly exempts them. Deviation from docs/01 §5 recorded in ADR-006. | low | accepted (ADR-006) |
