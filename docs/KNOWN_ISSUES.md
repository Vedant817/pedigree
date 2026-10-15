# Known issues and limits

Open items are tracked here (with a link to the failing test or the evidence). A feature
that cannot be finished goes here rather than being silently dropped.

| # | Date | Item | Severity | Status |
|---|---|---|---|---|
| 1 | 2026-10-15 | Development host is Windows; FalkorDB 4.22.1 runs via the pinned Docker image instead of the Linux `.so`+wheel path. The Linux/no-Docker path is shipped (`scripts/*.sh`) and is exercised by the production `Dockerfile`. | low | accepted (ADR-001) |
| 2 | 2026-10-15 | The user's home directory `C:\Users\vedan` is itself a git repository (no commits). The Pedigree repo is a separate repository nested inside it; git commands inside `pedigree/` use the local `.git`. | informational | noted |
| 3 | 2026-10-15 | FalkorDB Cloud Free tier has no TLS and no persistence; if used for the hosted demo it will hold synthetic demo data only. | low | documented |
