# F-03 - Revoke engine (barrier, fixpoint, compute, verify) + report + reinstate

Status: qa | Tests: `tests/integration/test_core_scenario.py`, `tests/unit/test_compute.py` | QA: pending `docs/qa/F-03.md`

## Behaviour (`engine/revoke.py`)
- `revoke(root_id, reason, dry_run=False, kind=revoke|supersede, hook=)`:
  1. Validates: root exists (`NotFoundInGraph`), is Source|Memory (`InvalidArgument`),
     reason <= 512 chars (`TooLarge`).
  2. CAS query `Q_REVOKE_ROOT`: sets `status='revoked'`, `revoked_at`, `reason`, clears
     `taint_parent`, and INSERTs the `Revocation` row `state='running'` - one atomic query.
     Idempotent: if the CAS matches nothing (already revoked) it returns the latest
     Revocation id with `idempotent: true` (no new row).
  3. `resolve()`: BARRIER fixpoint - `discover()` (BFS over mirrored FEEDS, unbounded
     depth via `algo.BFS($depth=-1)`) collects every descendant; every non-quarantined
     descendant is set `quarantined` in chunks of 2000 until a pass finds nothing to change
     (max 10 iterations). Because children inherit "quarantined from any revoked/tainted/
     quarantined parent", a concurrent ingest in the window is born quarantined: no leak.
  4. `compute_final` (pure, unit-tested): topologically orders the affected subgraph and
     assigns each node tainted (any path from a root, no healthy independent support),
     preserved (memory with >= 1 healthy corroborating Source), or ok (no path from any
     root). Records `taint_parent` = the shortest-path parent toward the root.
  5. WRITE phase: chunked `Q_WRITE_FINAL` (`status`, `taint_parent` via UNWIND `$b`);
     then a VERIFY loop (max 5): re-run discover + compute; if any quarantined remain, write
     again. `Revocation.state='done'` with counts (tainted/preserved/n_actions).
  6. Returns `{revocation_id, state, counts, actions, irreversible, artifacts, ms}`.
- Crash-safety: if the process dies between the CAS and the WRITE phase, affected nodes are
  already `quarantined` (excluded from retrieval) and the Revocation row stays `running`;
  `resume_incomplete()` finishes synchronously on the next start (tested).
- `dry_run=True`: same discovery + `compute_final`, NO write; returns would_taint /
  would_preserve / would_keep_ok and the action/artifact preview.
- `reinstate(root_id)` (corrected 2026-10-17 by P-012, ADR-015): `R := R \ {root_id}`, then
  recompute the whole status map from structure with `R` as the root set and `R ∪ {root_id}` as the
  discovery seed set (`resolve(..., roots=R, seeds=R ∪ {root_id})`). Nodes in `R` are **never
  reset** — a revoked root that is also a descendant of `root_id` stays `revoked`; only the named
  root's `revoked_at`/`reason` are cleared (`Q_REINSTATE_ROOT`, CAS on `status='revoked'`, which
  also writes the `reinstate` ledger row and supersedes a stale `running` revoke row). A root that
  is not currently revoked is an idempotent no-op (`remaining_roots` is still reported). Nodes
  outside `desc(R)` are `ok`. `report()`: by_status + revocation state counts.
- Corroboration is lazy: `corroborate()` writes the edge and leaves statuses unchanged until the
  next recompute (the next revoke/reinstate). "Healthy support" = a `CORROBORATED_BY` source whose
  status is `ok`; `by` and `integrity` do not enter the status recurrence.
- Per-tenant in-process `RLock` serialises concurrent revoke/reinstate in one process.

## Data model / Cypher touched
- `Q_REVOKE_ROOT` (CAS + Revocation insert), `Q_DESCENDANTS` (algo.BFS over FEEDS),
  `Q_QUARANTINE_CHUNK`, `Q_PARENTS_OF` (DERIVED_FROM), `Q_SUPPORT_OF` (CORROBORATED_BY +
  source status), `Q_WRITE_FINAL`, `Q_REVOCATION_SET_STATE`, `Q_REVOCATION_LATEST`,
  `Q_RUNNING_REVOCATIONS`, `Q_REINSTATE_ROOT` (CAS + reinstate ledger row),
  `Q_REVOCATION_SUPERSEDE`, `Q_STATUS_COUNTS`, `Q_REVOCATION_COUNTS`, `Q_ACTION_DETAILS`,
  `Q_MEMORY_ARTIFACTS`, `Q_INV_REVOKED_ORPHAN` (I-a).
  (`Q_REINSTATE_RESET` was deleted by P-012 — the blanket descendant reset was the bug.)

## Invariants
- No node may remain `quarantined` once a revocation reports `done` (verify loop).
- `taint_parent` chains are acyclic and end at a revoked root.
- I-a: every node carrying `revoked_at` has `status='revoked'`
  (`MATCH (n:Node) WHERE n.revoked_at IS NOT NULL AND n.status <> 'revoked'` == 0). This is the
  check that catches a revoked root silently clobbered to `ok` (the P-012 shape); a legitimate
  reinstate clears the marker, so history rows (`Revocation`) are never used for this.
- I-b: an `ok` node has no parent in `revoked|tainted|quarantined` (`Q_INV_OK_HAS_NO_BAD_PARENT`).
- I-c: a `preserved` memory has >= 1 corroborating source whose status is `ok`. A `preserved`
  node with a revoked ancestor is **correct** behaviour, not a violation.
- After `reinstate(r)` with no other active revocation, `check_invariants` is empty and every
  status is `ok`. With another revocation active, the remaining roots stay `revoked` and their
  descendants are recomputed under the remaining root set.

## Acceptance tests (AT0.2, AT0.5)
- `test_scenario_revoke_mix`: exact status map (m1 tainted, m2 preserved, m3 tainted,
  m4 ok, m5 ok, m6 tainted, a_commit+ a_push tainted), counts 5/1, actions list, and
  invariant check clean.
- `test_revoke_is_idempotent`, `test_dry_run_writes_nothing`,
  `test_race_child_created_mid_revoke_is_tainted` (hook seam),
  `test_reinstate_restores_everything`, `test_resume_incomplete_finishes_a_crashed_revocation`,
  `test_blame_chain_via_taint_parent` (`a_push -> m6 -> m3 -> m1 -> s_web`),
  `test_report_counts`, error cases in `test_ingest_and_revoke_errors`.
- `tests/unit/test_compute.py`: compute_final semantics incl. CycleError.

## Security notes
- Every query is static + parameterised; chunks <= 2000; no MULTI/EXEC anywhere.
- Revocation writes are idempotent and re-runnable; no destructive DELETE.
- `revoke` cannot target Actions (only Source|Memory are revocable).

## Evidence needed
- pytest output; independent probe re-deriving the post-revoke graph from the DB;
  crash-resume demonstration.
