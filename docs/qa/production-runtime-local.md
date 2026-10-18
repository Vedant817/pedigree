# Local production runtime verification

Date: 2026-10-18. This is orchestrator runtime evidence, separate from independent
security review and hosted release acceptance. The initial image predates later
capture/recovery integration; final-image verification remains required.

Command: `docker compose --env-file scratch/production.env -p pedigree-release-production up --build --wait`.
First build failed downloading a locked dependency. A direct container download
probe subsequently returned HTTP 200; the next build installed the frozen package
set and both owned services reported healthy. No dependency versions were changed.
Private generated credentials were supplied from an ignored file, never printed.

Command: `python scratch/verify-production-runtime.py` (the session harness is
retained in ignored scratch, not shipped as a package command). Its real HTTP
requests created an account and recorded the actual repository configuration-file
digest, an AST class-name observation derived from that file, and the file-inspection
action. No scenario seed or fabricated external action was used. The temporary
second isolation account was removed by exact created ID; the real inspection
workspace and its private credential file were retained locally.

Observed result, exit 0:

```json
{"unauthenticated_graph_denied":true,"empty_first_boot":true,"whatif_preserves_graph":true,"revoked_dependency_blocks_action":true,"invariants_clean":true,"foreign_tenant_cannot_read_source":true,"unknown_is_not_in_graph":true,"api_database_restart_preserves_graph":true,"persisted_nodes":3,"persisted_edges":2}
```

The harness restarted only its own Compose database/API services, waited for
readiness, and compared persisted graph projections and invariants. The original
crashed database volume was never mounted, deleted or reseeded. This is orderly
restart persistence, not host-crash durability or off-host disaster recovery.

Local browser testing service runs reported `passed`, but their recorded steps
covered only part of the authored assertions. Run `6998e28b-3fb4-4eac-b83e-e18c276aa3f9`
explicitly navigated, filled an invalid credential, clicked Connect, navigated again
and recorded empty-input/disabled-preview assertions. Full scenario coverage remains
inconclusive; no PR-preview-triggered test result is claimed.

The harsh-user harness initially exposed a child-environment bug: it discarded the
selected database port and tried the unavailable default listener. The regression
test fails before `child_environment` exists. After correction, `make dogfood`
returned `PASS=23 FAIL=0 EXPECTED-FAIL=0 STALE=0 SKIP=0`, exit 0. Cleanup returned
the owned graph/registry state to its baseline.
