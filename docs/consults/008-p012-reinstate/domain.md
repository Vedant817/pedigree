# Consult 008 — P-012: `reinstate` must not un-revoke other roots

Repo: `C:\Users\vedan\Documents\Resources\Code\pedigree` · Engine: pinned FalkorDB v4.22.1
(docker `falkordb/falkordb:v4.22.1`, container `pedigree-db`; module version 42201 verified in-run).
Preflight: `docs/tech/TECH_REFERENCE.md` §3/§5 and `GOTCHAS.md` were read first. They give traversal
and atomicity ground truth but **not** reinstate semantics; `TECH_REFERENCE.md:58` only points to
`tech/examples/py/03_provenance_cascade.py:70-74` ("reset all descendants, then re-run the cascade
for every source that is still retracted"). This consult was therefore needed.

## 1. What `reinstate` is supposed to mean (spec reading)

- Contract — `docs/01-IDEA.md:141`: "**Reinstate(root):** BFS descendants of root *before* flipping;
  set root `ok`; reset those descendants to `ok`; then re-run steps 2-7 for the remaining revoked
  roots (idempotent)."
- Status semantics — `docs/01-IDEA.md:124-125`: "Let R be the set of revoked roots (Sources or
  Memories). ... `bad(m)` = any DERIVED_FROM parent that is in R or finally `tainted`. If `bad(m)`
  is empty -> `ok`. Else if m has a healthy CORROBORATED_BY source (status `ok`) -> `preserved` ...
  Else -> `tainted` with `taint_parent` = one bad parent. Note a node whose only bad parent became
  `preserved` is simply `ok`."
- F-03 spec — `docs/features/F-03-revoke.md:31-33`: "`reinstate(root_id)`: resets the root +
  descendants to ok, clears taint_parent, re-resolves **remaining** revoked roots". Invariant
  `F-03-revoke.md:45`: "After `reinstate`, `check_invariants` is empty and all statuses are `ok`
  (**given no other revocation is active**)." The P-012 repro is exactly the "another revocation is
  active" case.
- Oracle — `engine/compute.py:1-9,62-90`: revoked roots keep their status and are never rewritten
  (`compute.py:82-83`); every member is recomputed from parents in topological order. So any node
  whose status was produced under the undone root must be recomputed under the *still-active* root
  set, and a revoked root that remains active stays `revoked`.
- Intended pattern — `tech/examples/py/03_provenance_cascade.py:70-74`: reset descendants, then
  "re-run the cascade for every source that is still retracted" — remaining roots are the still-
  retracted ones, not "whatever `status='revoked'` remains after the reset".
- Audit — `AUDIT.md:118`: expected `A=ok, B=revoked, Cc=tainted`; current code yields
  `A=ok,B=ok,Cc=ok`; `check_invariants` returns `[]`; cited probe `p03_output.txt`: 22/150 random
  trials diverge (not in repo; not re-run).

Current defect (static): `reinstate()` runs `discover(root)` -> `Q_REINSTATE_ROOT` -> blanket
`Q_REINSTATE_RESET(descendants)` -> *then* `revoked_roots()` (`engine/revoke.py:276-280`). The reset
(`db/queries.py:238-239`) sets every descendant `status='ok', taint_parent=NULL`; `revoked_roots()`
is `MATCH (r:Node {status:'revoked'})` (`queries.py:196`), so a descendant that was itself a revoked
root is erased from R **before** the re-resolve.

## 2. Ground truth on the real server (2026-10-16)

Scripts: `scratch/cons008_repro.py`, `scratch/cons008_scale.py`, `scratch/cons008_write.py`.
Graphs `ped:cons008repro`, `ped:cons008scale`, `ped:cons008write` created and deleted afterwards;
`ped:cons008arch` (not created here) left untouched.

### (a) Deterministic repro through the engine functions (real output, condensed)

```
=== after revoke(A) ===  statuses: {'A':'revoked','B':'tainted','Cc':'tainted'}
=== after revoke(B) ===  statuses: {'A':'revoked','B':'revoked','Cc':'tainted'}
  revocations [id, root_id, state, n_tainted, n_preserved]:
    [rev_3fd768ce8846c3e8,'A','done',2,0], [rev_12c7316d29a65e71,'B','done',1,0]
=== after reinstate(A) === statuses: {'A':'ok','B':'ok','Cc':'ok'}
  reinstate(A) returned: {"dry_run":false,"root_id":"A","reset":2,"remaining_roots":0,
                          "counts":{"tainted":0,"preserved":0,"ok":0}}
  compute_final(roots={B}) says: {'Cc': ('tainted','B')}
```
`check_invariants` was `[]` at every snapshot (baseline, after each revoke, after reinstate).

### (c) Property left behind by the blanket reset

After `reinstate(A)`, node **B** — a self-revoked root now "ok" — keeps its revoke metadata, because
`Q_REINSTATE_RESET` only clears `status`/`taint_parent`; `revoked_at`/`reason` are cleared only by
`Q_REINSTATE_ROOT` on the named root:

```
props B: {... "reason":"cons008 B", "revoked_at":1792147864912, "status":"ok" ...}
props Cc: {... "status":"ok"}            # taint_parent removed (was 'B')
revocations: [rev_...'A','done',2,0], [rev_...'B','done',1,0]   # B's row untouched
check_invariants: []
```
Inconsistencies left: `B.status='ok'` + `Revocation{root_id:'B', state:'done'}` +
stale `revoked_at`/`reason` on B; Cc has no `taint_parent` although its only parent still carries
an active revocation record. `Q_INV_OK_HAS_NO_BAD_PARENT` (`queries.py:364-367`) only checks parent
*status*, and `Q_INV_REVOKED_SHAPE` (`queries.py:318-322`) only checks revoked nodes, so nothing flags it.

### (b) Subtree fetch cost (2001 nodes, 5200 FEEDS edges, 5 layers x 400, 3 parents/node; 48.4k paths)

```
algo.BFS Q_DESCENDANTS (-1, id+status):        rows=2000  median 14.31 ms (min 13.73, max 20.50)
var-length FEEDS*1..12 DISTINCT (id+status):   rows=2000  median 26.53 ms
var-length FEEDS*1..5  DISTINCT (id+status):   rows=2000  median 24.77 ms
var-length FEEDS*1..12 count(*):               median 7.96 ms
Q_DESCENDANT_COUNTS (batched BFS size, 3 roots): median 1.80 ms
```
`Q_DESCENDANTS` (BFS) is the efficient id+status primitive; var-length + `DISTINCT` is usable but
~2x slower here and grows path-wise on denser DAGs (`GOTCHAS.md` #5). One BFS per *still-active*
root suffices; per-node intersection is free in Python.

### Write / atomicity measured (2000 ids)

```
Q_REINSTATE_RESET 2000 ids (1 query): median 15.73 ms
Q_WRITE_FINAL     2000 rows (1 query): median 22.72 ms
```
One query (incl. UNWIND batches, multi-clause writes) is atomic; MULTI/EXEC is not
(`GOTCHAS.md` #7; `TECH_REFERENCE.md:70` [V]); chunks <= 2000.

## 3. Prior art (brief)

- Internal: **MemoRepair** (`docs/research/01-prior-art.md:49`): "Barrier-first withdrawal then
  rebuild of **only validated successors**; exact min-cut selector" — un-revocation must re-derive
  only what is still supported. In-event: **kintsugi** (`01-prior-art.md:57`) re-runs "only those
  actions against clean memory"; **undograph** (`:58`) does "selective repair" after an operator
  corrects a source; **PACMI** (`:48`) advertises "cascading invalidation, preserves history".
  None cited describes re-validating a revoked node that has its own revocation record.
- External: W3C PROV-DM §5.1.8 (https://www.w3.org/TR/prov-dm/#term-invalidation): "Invalidation is
  the start of the destruction, cessation, or expiry of an existing entity by an activity. The
  entity is no longer available for use (or further invalidation) after invalidation. Any
  generation or usage of an entity precedes its invalidation." PROV models invalidation as a
  per-entity event with no un-invalidation primitive; undoing one invalidation requires recomputing
  which downstream entities remain invalid under the still-invalidated set.

## 4. Facts for the architect (no design decisions)

1. **Root set source of truth.** `revoked_roots()` = `Node.status='revoked'` only (`queries.py:196`).
   Revocation rows are history (`state` in running|done; no `reinstated` state); `Q_REVOCATION_LATEST`
   / `Q_RUNNING_REVOCATIONS` exist (`queries.py:221-233`) but no query maps "row still active" to a
   root set. Any reset of a self-revoked descendant removes it from R.
2. **What must be recomputed.** Per `compute.py:62-90`: for every node reachable via FEEDS from any
   still-active revoked root — final `status` + `taint_parent`, topologically. No bad parent -> `ok`;
   memory with a healthy `CORROBORATED_BY` source -> `preserved`; a node whose only bad parent became
   `preserved` -> `ok` (`compute.py:8-9`). The repro's expected `B=revoked, Cc=tainted` follows from
   R={B}: `compute_final` returns `Cc: tainted, taint_parent='B'` (verified).
3. **What must never be blanket-reset.** (i) A node that is itself an active revoked root;
   (ii) `revoked_at`/`reason` must not survive a transition to `ok` (measured stale on B);
   (iii) Revocation rows must stay consistent with node status (B's row stayed `done` while
   `B.status='ok'`).
4. **Discovery primitive.** `algo.BFS` over outgoing FEEDS, depth -1 in the engine
   (`queries.py:165-168`); it excludes the start node (`GOTCHAS.md` #6), so the root is handled
   separately. `docs/01-IDEA.md:121` says the product default depth is 12 with truncation reporting,
   while the engine passes -1.
5. **Cost / atomicity.** 2k-node subtree BFS ~14 ms; 2k-row final write ~23 ms; reset write ~16 ms;
   all single queries atomic, chunks <=2000, no cross-query transaction (`GOTCHAS.md` #7). So
   multi-step reset-then-resolve has no atomicity backstop: a crash between reset and re-resolve (or
   after the root flip) leaves mixed statuses. `reinstate` writes no `running` record, so
   `resume_incomplete()` (`revoke.py:299-308`) recovers only crashed `revoke`s.
6. **Concurrency.** Only revoke/reinstate/resume take `tenant_lock` (`revoke.py:123,267,304`);
   `engine/ingest.py` contains no `tenant_lock` (grep: 0 matches). A child created under a parent
   still marked revoked is born quarantined (`queries.py:97-99`); if it arrives after the pre-flip
   snapshot and is not a descendant of a remaining root, nothing re-resolves it. Revoke closes the
   analogous window with the barrier (`F-03-revoke.md:13-17`); reinstate has no barrier. Runtime
   consequence not executed here: [U].
7. **Invariant gap.** `Q_INV_OK_HAS_NO_BAD_PARENT` (`queries.py:364-367`) only looks at parent
   `status`; the repro passes because the revoked ancestor's status was reset too. `FIX_PROMPT.md:71`
   asks for "no node is `ok`/`preserved` while being a revoked root or having a revoked ancestor
   lacking trusted support". Verified: `check_invariants == []` on the broken state.
8. **Numbers to move.** `AUDIT.md:118`: "22/150 randomized trials differ from the oracle"; the
   deterministic repro differs deterministically. Not re-run in this consult.

## Limits / confidence

- [V] every file:line quoted; all experiment numbers above are from the real pinned server, scripts
  in `scratch/cons008_*.py`, graphs deleted.
- [U] the 22/150 count is cited from `AUDIT.md:118`, not re-run (the deterministic repro reproduces
  the class). Race consequence in fact 6 is code-reading, not an executed race.
- [V/D] PROV-DM quote fetched from the official W3C page; it is a documented model, not a test result.

**What would change my mind:** a repo doc stating that `reinstate(root)` intentionally cancels every
revocation in the subtree (none found — all three internal sources say "remaining revoked roots"),
or a test asserting `B=ok` in the repro shape (only `test_reinstate_restores_everything` exists, with
a single root: `tests/integration/test_core_scenario.py:142-151`).
