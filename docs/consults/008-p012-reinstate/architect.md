# P-012 consult — architect recommendation (reinstate must not un-revoke other roots)

- **Provenance:** the `senior-architect` subagent hit its step limit before writing this file; the
  orchestrator transcribed its final analysis verbatim-in-substance. All code/cost facts below were
  verified by that session against the pinned FalkorDB (scratch graph `ped:cons008arch`, created
  and deleted; module 42201).
- **Sibling consults:** `domain.md` (semantics + cost + stale-metadata facts), `oracle.md`
  (verification plan review, verdict NOT YET + corrections).

## Recommendation (decision-first)

**One shared helper `rederive(db, gname, *, roots, seeds)`** — a generalization of the existing
`resolve()` loop (barrier -> `compute_final` -> chunked write -> verify) with an explicit `seeds`
parameter, default `seeds=roots`.

`reinstate(root)` becomes:

1. one atomic CAS query (`Q_REINSTATE_ROOT`, changed: only if `status='revoked'`; clears
   `revoked_at`/`reason`/`taint_parent`; creates `Revocation{kind:'reinstate', state:'running'}`);
2. `roots = revoked_roots()` (now correct — nothing was blanket-reset first);
3. `seeds = roots ∪ {root_id}`;
4. `rederive(roots=roots, seeds=seeds)`; then `_finish`.

**Delete `Q_REINSTATE_RESET` entirely** — the blanket reset *is* the bug: it wipes B's
`status='revoked'` before `revoked_roots()` is read (`revoke.py:276-280`), so B vanishes from the
root set (`remaining_roots=0` in the domain repro).

**Why the union closure is the smallest provably correct scope:** members = closure(roots ∪ {A}).
Every bad parent of a member is itself a descendant of a revoked root (in members), so boundary
statuses are never trusted; every node outside is already `ok`. `compute_final` skips roots and
`Q_WRITE_FINAL` carries `WHERE n.status <> 'revoked'`, so a revoked root can never be written back
to `ok` (fail-safe by construction). Repro trace: after `reinstate(A)`, roots={B}; A re-derives to
`ok`; B skipped; Cc's parent B ∈ roots => `tainted`. The union with closure(roots) is required
because a member whose bad parent lives in another revoked root's closure needs that parent's
*final* status, not its stale one.

**Implementation note (measured):** `algo.BFS` excludes the start node — `rederive` must add the
seeds explicitly to the member set.

## Empirically rejected options

- **(B) "reset only sole-taint-root nodes"** — needs per-node ancestor classification, i.e. the same
  closure + topo propagation plus extra queries; a naive per-node `Q_ANCESTORS` BFS is
  O(members × BFS) ≈ 10 000 × 140 ms — catastrophic. No cost advantage.
- **(C) global full-graph sweep** — correct and self-healing of legacy corruption, but O(|V|) on a
  user mutation path, rewrites/quarantines healthy nodes, widest concurrency window. Keep only as
  `reconcile --repair`/`--full` tool, never on the `reinstate` path.

## Unified recovery model (P-011 + P-012 + P-024 compose)

One helper, four call sites:

| Call site | roots | seeds | ledger |
|---|---|---|---|
| `revoke` | roots | = roots (default) | existing `kind='revoke'` row |
| `reinstate` | `revoked_roots()` | roots ∪ {A} | `kind='reinstate'` row |
| `resume_incomplete` | per running row | roots ∪ {row.root_id} | works for both kinds |
| `reconcile` | `revoked_roots()` (only when no running row) | roots ∪ {quarantined ids} | none |

Single definition of the root set: `Q_REVOKED_ROOTS` (= all individually marked revoked nodes; the
two sets are identical in this data model). Reinstate must supersede any running revoke rows for
the same root (`state='superseded'`), and `Q_REVOCATION_LATEST` must filter
`kind IN ['revoke','supersede']` so `revoke()` idempotency is not confused by reinstate rows.

## Timing evidence (pinned FalkorDB, 20k-node graph = two 10k chains)

| Step | Measured |
|---|---|
| BFS per root | 115–140 ms |
| 20 000-member union closure | (same BFS envelope) |
| `Q_PARENTS_OF` (10 chunks) | 288 ms |
| `Q_SUPPORT_OF` | 126 ms |
| `Q_QUARANTINE_CHUNK` | 280 ms |
| `Q_WRITE_FINAL` (chunk=2000) | 355 ms |
| **Full rederive pass** | **≈1.3 s**; 2–3 passes typical => ~2–4 s per 20k reinstate |
| `Q_REVOKED_ROOTS` | 5.6 ms |

Reinstate cost therefore grows with the total revoked closure, not the subtree — bounded by
node_cap.

## Required invariants / tests

1. Deterministic repro => `A=ok, B=revoked, Cc=tainted`, `check_invariants == []`.
2. 300+ hypothesis examples vs `tests/oracle.py` after every op (see `oracle.md` corrections:
   lazy corroboration, pinned semantics, slow marker).
3. Crash injection after CAS / after barrier / mid-write => resume yields oracle-equal statuses,
   zero `quarantined`.
4. Concurrent ingest under A during reinstate => zero stuck quarantined.
5. A concurrent revoke of the reinstated root landing mid-flight must leave it `revoked`.
6. New invariant: with no running Revocation, the stored status of every node in closure(revoked
   roots) equals `compute_final` (read-only, via a `plan()`-style helper); a fabricated old-bug
   state must be flagged; reverting the fix fails it.
7. `reinstate` on a non-revoked node is an idempotent no-op; dry-run writes nothing.

## What could still be wrong (risk list)

1. **`corroborate` does not recompute** (`Q_CORROBORATE` only adds the edge — verified by the
   oracle consult too: statuses change only on the next recompute). A random corroborate step in
   the property test will diverge from the oracle unless `corroborate` also calls
   `rederive(seeds={m})` — decide jointly with the oracle/test owner (product semantics).
2. **Legacy corruption from the old bug** (tainted nodes with no revoked ancestor) is outside the
   union closure and stays wrong — needs the option-(C) sweep as `reconcile --repair`, or an
   explicit known-issue.
3. `tenant_lock` is in-process only; cross-process revoke/reinstate interleaving converges only
   after a reconcile (fail-safe direction held by the `status <> 'revoked'` write guard).
4. The new invariant must be skipped while a Revocation is `running` (quarantine states would
   false-positive).
5. Superseding running revoke rows must be exercised (crash of reinstate -> resume must not
   resurrect the superseded revoke wrongly).

## Reversibility

Localized to `revoke.py` + 3–4 queries + one `check_invariants` addition; no data migration
(schema-less). Revert = single commit. Reinstate ledger rows are additive nodes.
`Q_REINSTATE_ROOT`/`RESET` names retained where sensible for a minimal diff
(`Q_REINSTATE_RESET` deleted as dead after the fix).
