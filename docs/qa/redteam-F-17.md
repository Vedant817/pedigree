# F-17 local red-team review

Attack boundary: local FalkorDB and isolated test tenants only. No external actions.

| Finding | Repro/test | Severity | Proposed fix |
|---|---|---|---|
| F17-01 response lies after delete failure | test_whatif_cleanup_failure_must_not_report_deleted; inject delete failure on actual copied graph, assert graph remains then assert copy_deleted=False | HIGH | Return truthful cleanup status and retain orphan tracking/retry rather than silent success |
| F17-02 untracked fresh copy deleted | test_whatif_fresh_untracked_copy_must_survive_reaper; real GRAPH.COPY then reap_stale immediately | HIGH | Persist lease/expiry in copy; only remove demonstrably expired copy or own known inactive cleanup orphan |
| F17-03 raw copy DB exception | test_whatif_copy_db_error_is_mapped; deterministic redis ResponseError injection; real concurrent calls also yielded could-not-fork | MEDIUM | Map DB exceptions to typed sanitized unavailable errors |

Reproduction command: `.\.venv\Scripts\python.exe -m pytest tests/security/test_whatif_audit_review.py -q -rx -s`.
Before fixes: `26 passed, 4 xfailed in 5.23s` (includes F18 test). Auth/root injection/concurrency/copy-failure tests are local runtime evidence; cross-worker consequence is an inference, with newly created untracked-copy deletion directly reproduced. See F-17.md for verbatim commands, cases and residual risks. Pending repair verification; no production verdict.


## Independent repair verification (final)

Commands re-run after production fixes:
```
.\.venv\Scripts\python.exe -m pytest tests/integration/test_whatif.py tests/integration/test_audit.py tests/security/test_whatif_audit_review.py -q -rx -s
.\.venv\Scripts\python.exe -m ruff check tests/security/test_whatif_audit_review.py tests/integration/test_whatif.py
.\.venv\Scripts\python.exe scripts/secret_scan.py --history
```
Observed output:
```
Observed typed concurrent snapshot failure: what-if snapshot unavailable
45 passed in 7.21s
All checks passed!
[secret-scan] PASS: no credential shapes found in tracked files or git history
```
The scanner PASS was from the preceding post-fix run (44 passed before the final extra lost-response regression); the last change added only that review test. All four original expected-failure regressions now pass with no xfail markers. The retained tests proved the defects before repair and now guard the expected behavior.

F17-01 resolved locally: injected cleanup failure reports copy_deleted=False and cleanup_error, retains an actual copy plus pending cleanup capacity, then a retry removes the graph and releases capacity. Two cleanup failures occupy both slots until retry. F17-02 resolved locally: unknown fresh copy and another worker's unexpired lease survive, expired lease is reaped. F17-03 resolved locally: injected redis copy failure and actual concurrent local fork failure become typed unavailable. Lost-copy-response injection first creates a real graph then raises ConnectionError; cleanup deletes that exact graph and releases tracking. Snapshot-baseline regression inserts a real source immediately before copy and proves it is unchanged rather than incorrectly counted as a simulation effect. Original full source node/edge snapshots remain unchanged on ordinary preview/failure paths.

Contract amendment: the original integration stale-copy fixture now adds an explicit expired WhatIfLease to the test-owned copy and uses finally cleanup. Previously it incorrectly treated any unmarked fresh copy as stale. Unknown legacy copies deliberately require operator cleanup. Root limit is now five, matching LIMITS and request schema.

Final verdict: PASS for the tested local implemented subset. Per-tenant concurrency is enforced per process; a global cap across independent workers is NOT implemented or proven. Lease age tests simulate another worker's persisted metadata, not an actual second worker process. No production, huge-graph, process-crash, or checkpoint/restore claim. Checkpoint/restore remains UNBUILT.
