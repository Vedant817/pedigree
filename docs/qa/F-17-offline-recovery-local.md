# Offline checkpoint recovery: local implementation evidence

Date: 2026-10-18. Builder evidence, independent QA pending.

Baseline: isolated branch `t3/checkpoint-recovery`, fast-forwarded to release commit
`2947c30`. Imported the complete tracked HEAD diff of the authorized recovery files;
preserved release WCC and capture receipt constants at the query append conflict.
Original worktree, staging area and old `pedigree-dbdata` were not modified.

Environment: Python 3.12.15; `PYTHONPATH=src`; `FALKOR_HOST=127.0.0.1`;
`FALKOR_PORT=6386`. Dedicated container `pedigree-checkpoint-db-6386`, image
`falkordb/falkordb:v4.22.1`, owned volume `pedigree-checkpoint-6386-data`;
AOF enabled with every-second fsync and explicit WAITAOF per mutation. No test
commands intentionally run concurrently. A mistakenly started second regression
process was stopped; the initial run is retained below as contaminated evidence.

Commands use the existing project virtualenv Python (no environment install).

## Reproduced defect

`python -m pytest -q tests/integration/test_checkpoint_recovery.py -k rollback_choice`
on imported recovery behavior: **1 failed, 19 deselected in 14.88s**, exit 1.
An interrupted forward restore followed by an interrupted explicit rollback and plain
recover produced the checkpoint fingerprint instead of the previous-main fingerprint.
The fix journals the rollback direction with conditional SET and same-connection
WAITAOF before replacement.

Initial imported focused suite: **1 failed, 19 passed in 156.97s**, exit 1.
The failure was `GRAPH.COPY failed, could not fork` during the brief accidental test
overlap. This is not a passing validation result. The journal was retained; reruns
must remain serial and no production retry-by-deletion is introduced.

## Acceptance scope

Real DB equality of graph nodes/edges, retained rollback, immutable names, snapshot
cap, missing main, unhealthy-main forensic retention, tenant listing boundary,
quota mutex confirmation/owner compare-and-delete, failure injection before/after
copy and RENAME, killed Python process, explicit rollback interruption, capture receipt
rewind, and actual DB crash/AOF recovery. Unit tests cover missing admin/quiescence
and failed WAITAOF. Name namespace invariant uses Hypothesis.

The DB crash test runs only when the explicitly owned container is selected through
`PEDIGREE_CHECKPOINT_RESTART_CONTAINER=pedigree-checkpoint-db-6386`; it checks port
6386 before `docker kill` and `docker start`. Both pre-RENAME and post-RENAME
interruptions retain the exact journal, main fingerprint and rollback across crash,
then complete recovery. This is DB restart evidence, distinct from Python restart.

## Limits and release gates

Offline operator quiescence is required and cannot be proven by the CLI flag.
Recovering a still-running maintenance operation is unsupported operator misuse.
Healthy invariants are required to reopen a forensic rollback. Graph receipts rewind
with tenant lineage; external spools and acknowledged deliveries need reconciliation.
Same-host snapshots do not protect against disk loss. No hosted deployment, PR,
third-party automated suite or independent QA pass is claimed. No push requested.

## Additional failure reproduction and persistence investigation

`python -m pytest -q tests/integration/test_checkpoint_recovery.py -k
'aof_journal and after or rejected_unhealthy' -x`: **1 failed, 1 passed,
20 deselected in 24.65s**, exit 1. The post-RENAME DB crash test passed. The
new rollback-rejection test failed because unhealthy rollback was durably selected
before invariant validation. Validate the candidate before recording direction.

On the initial test-history volume, the second hard restart exited **139** during
AOF replay in `GraphContext_GetSchemaByID+0x4b`; current command was GRAPH.EFFECT
for the already-deleted session sentinel graph. Its AOF contains initial effects at
commands 9-21, GRAPH.DELETE at 502, then further schema effects at 1062-1063.
The crash therefore cannot be attributed to RENAME alone. Preserved the stopped
container as `pedigree-checkpoint-crashed-aof-6386` and its owned volume; copied AOF
outside the repository for analysis. Original production volumes remain untouched.

A second fresh owned volume `pedigree-checkpoint-6386-probe-data` on the same port
passed the isolated before-RENAME crash case: **1 passed, 21 deselected in 14.47s**.
The subsequent after-RENAME crash case also passed in the combined command above.
These isolated passes do not erase the historical-AOF crash; consolidated restart
validation is required before a safety claim.

The combined focused run on the second volume was stopped after the same DB AOF
replay exit 139 (no passing suite count claimed). The new crash targeted another
already-deleted session sentinel. Preserved that container as
`pedigree-checkpoint-crashed-probe-6386`. Final verification uses a third fresh owned
volume `pedigree-checkpoint-6386-final-data` and the original dedicated container name.

Mitigation under test: `_ready` finishes a fresh BGREWRITEAOF generation before
reservation or recovery, with a bounded wait and explicit failure. No GRAPH.COPY
fork overlaps the rewrite. Existing journals remain present through compaction.
This is database-wide offline maintenance, not a version upgrade or repair of old
production storage. A unit failure injection rejects a failed rewrite command.

Integration coordination: aggregate release gate is root-owned. Root identified the
existing CI database startup lacks REDIS_ARGS enabling AOF and will fix that during
integration. Recovery intentionally fails without AOF; no CI workflow changes or
unrelated stdio/WCC patches enter this scoped commit. Hard container restart tests
remain explicitly opt-in; ordinary checkpoint integration tests still require AOF.

## Final local results

With `PYTHONPATH=src`, `FALKOR_HOST=127.0.0.1`, `FALKOR_PORT=6386`, and
`PEDIGREE_CHECKPOINT_RESTART_CONTAINER=pedigree-checkpoint-db-6386`:

`python -m pytest -q tests/unit/test_checkpoint_cli.py
 tests/unit/test_checkpoint_persistence.py tests/integration/test_checkpoint_recovery.py`
— **26 passed in 236.17s**, exit 0. Includes both hard DB crash cases, killed Python,
repeated rollback interruption and rejected unhealthy rollback; no skips.

After adding the explicit missing-AOF rejection regression:
`python -m pytest -q tests/unit/test_checkpoint_cli.py tests/unit/test_checkpoint_persistence.py`
— **5 passed in 0.33s**, exit 0. These runs cover **27 unique final tests** (22
integration and 5 unit); four unit cases overlap between the two commands.

`python -m ruff check .` — **All checks passed!**, exit 0.
`git diff --check HEAD` — exit 0 (only working-tree line-ending notices).
Original authorized diff SHA-256 still equals the import patch SHA-256 after all work;
the original tracked edits and staging were not changed.

The full aggregate gate was deliberately left to root following integration steering;
no full-suite result or hosted CI result is claimed here. Root owns CI AOF enablement,
aggregate testing and independent review. The mitigation passed repeated crash cases,
but does not repair an already crash-damaged AOF volume or fix all upstream engine
persistence behavior. Both failed owned test volumes remain preserved for diagnosis.

Staged-file hygiene: `scripts/secret_scan.py` PASS (no credential shapes);
`scripts/check_numbers.py` PASS (4 files, 70 allowed values);
`scripts/check_readme.py` PASS (11 headings, links and numbers), each exit 0.
