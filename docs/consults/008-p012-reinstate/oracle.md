# Oracle review — P-012 `reinstate` (eval-statistician consult)

Reviewed: 2026-10-16 · repo HEAD `44cf5bf` (P-012 not yet implemented) · read-only on `src/`/`tests/`.
Read: `FIX_PROMPT.md` B2 (68–72), `engine/compute.py`, `engine/revoke.py`, `engine/ingest.py`,
`db/queries.py`, `db/schema.py`, `docs/01` §6.1/§6.3, `docs/02`, `docs/03`, `docs/features/F-03`,
`tests/unit/test_compute.py`, `tests/evals/test_oracle_agreement.py`, `evals/oracle.py`, `AUDIT.md` P-012,
`docs/consults/008-p012-reinstate/domain.md` (do not duplicate; see it for the static defect).
Ran: 3 probes on pinned FalkorDB 42201, hypothesis 6.169.4, throwaway tenants `cons008or*`/`cons008tm*`
(all deleted). No source edited.

## 1. Verified facts (probe evidence; my probes, not re-cited audit numbers)

| # | Probe | Verified result |
|---|---|---|
| F1 | A→B→Cc; revoke A; revoke B; reinstate A | `A=ok, B=ok, Cc=ok`, roots `[]`, `check_invariants == []` — bug reproduced exactly; matches domain.md |
| F2 | same state | B keeps `revoked_at`+`reason` while `status='ok'`; `Revocation` rows for A and B remain (`done`); `revoked_at IS NOT NULL AND status<>'revoked'` → **1** (B); `Revocation.root_id` not revoked → **2** (A is legitimately reinstated) |
| F3 | S2→M1; revoke S2; `corroborate(M1,S3,by=human)` | M1 stays `tainted` after corroborate (**lazy**: no recompute); a later recompute with S3 healthy produced `preserved`; support from a revoked source stayed unhealthy |
| F4 | `reinstate(never-revoked M1)` | `reset=0`, statuses unchanged |
| F5 | timing envelope (5× fresh graph+2 nodes+drop): 28–44 ms; 12-node build 28 ms; small revoke 17 ms; status read 1 ms | 300 DB-backed examples ≈ 1–4 min → §4 budget |

F2 is load-bearing: `revoked_at` is the **only** reliable in-graph marker of "individually revoked and not
formally reinstated" — Revocation rows persist across legitimate reinstate, so a row-based invariant
false-positives on the reinstated root.

## 2. Rules that are ambiguous/under-specified — pin each before writing the oracle

**R1 · Reinstate is mis-specified in the product docs.** `docs/01` §6.3 ("reset those descendants to
`ok`; then re-run steps 2–7 for the remaining revoked roots") and F-03 ("resets the root + descendants
to ok") describe the buggy algorithm; a literal from-scratch oracle would bless `B=ok`. Oracle reading
(per AUDIT P-012 + domain.md §1): `reinstate(r)` = `R := R \ {r}` then recompute the whole map from
structure; nodes in `R` are never reset (a revoked root wins); descendants are recomputed under the
remaining root set. **The oracle must not be written from §6.3 as it stands** — edit `docs/01` §6.3 and
F-03 in P-012 and record a DECISIONS entry.

**R2 · Corroboration timing is unspecified and the engine is lazy (F3).** The plan's "after EACH step
compare … to the oracle" is ill-defined: a pure oracle applying the new support immediately says
`preserved`, the engine says `tainted` until the next revoke/reinstate. Interpretation to encode: support
is effective as of the last **recompute** (revoke/reinstate); after a corroborate step the driver asserts
statuses are **unchanged** and folds the edge in for the next recompute. Alternative (stronger, out of
scope): make `corroborate` recompute. Document whichever is chosen (docs/01 §6.1 + DECISIONS); otherwise
the property test is red for the wrong reason.

**R3 · "trusted support" is the wrong rule word.** Status semantics: `preserved` iff the node has a bad
parent and a `CORROBORATED_BY` source whose **status is `ok`** (docs §6.3; F3). `by`
(agent/human/scanner) and `integrity` do not enter the status recurrence (ADR-007 gates; P-015/C1 is
roles). Oracle uses the status-ok rule; invariant text says "healthy (status ok) corroboration".

**R4 · `quarantined` is a transient barrier state, never an oracle output.** After a quiescent op (no
concurrent writer) no node may remain quarantined; a quarantined node is itself a divergence. P-024's
invariant covers that class separately.

**R5 · Marker lifecycle.** Rows are audit history (F2); `Q_REINSTATE_ROOT` clears `revoked_at/reason` for
the reinstated root only. Drive the oracle's `R` from the driver's own model, but cross-check
`set(db statuses == revoked) == R` after every op; the graph invariant needs `revoked_at` (§6).

**R6 · No-op ops are in scope.** `revoke(already-revoked)` is idempotent; `reinstate(never-revoked)` is a
no-op under correct global semantics (F4). Model `reinstate(x)` as `R −= {x}` unconditionally and compare
maps anyway; include both in generation.

**R7 · Precedence order (explicit).** (1) `r ∈ R ⇒ revoked` (root wins even if also a descendant);
(2) descendants not in R: any parent finally `revoked|tainted` ⇒ bad path → `preserved` if some support
source ∉ R else `tainted`; (3) nodes outside the descendant union ⇒ `ok`; (4) never emit `quarantined`.
A `preserved` parent is **not** bad — its children can be `ok` (that is the feature; do not "fix" it).

**R8 · An independent oracle already exists.** `evals/oracle.py` (brute-force fixpoint, no engine
imports) is guarded by `tests/evals/test_oracle_agreement.py` on 1000 DAGs; `tests/unit/test_compute.py`
has a second brute-force implementation. The plan's `tests/oracle.py` would be a third. Either extend
`evals/oracle.py` with the global/multi-root API, or keep `tests/oracle.py` + add a drift-guard test
against `evals.oracle.ground_truth` on its valid domain (single root, all statuses ok). Caveat:
`evals/oracle.ground_truth` treats a `statuses`-revoked node that is NOT in `roots` as `ok` (it skips it
and never marks it bad), so it must only ever be called with the full active `R`, never with stale
per-node statuses. Record the choice in `docs/fixes/P-012.md`.

## 3. Oracle pseudocode (pure; imports nothing from `pedigree`)

```
IN  nodes:   id -> kind ∈ {source,memory,action}
    parents: child -> [parent]        # DERIVED_FROM, DAG by construction
    support: memory -> [source]       # CORROBORATED_BY
    R:       set of active revoked roots (driver model)
OUT status:  id -> {ok|revoked|preserved|tainted}      # never quarantined

assert R ⊆ nodes and kinds(R) ⊆ {source, memory}
assert support keys are memories and targets are sources
desc = nodes reachable from any r∈R by following parent edges downward   # descendants
status = {n: "ok" for n in nodes}
for r in R: status[r] = "revoked"                    # (1) root precedence
repeat until stable:                                 # (2) monotone recurrence, sweep (not Kahn)
    for m in desc \ R:
        bad = [p for p in parents[m] if status[p] in {"revoked", "tainted"}]
        status[m] = "ok" if not bad else \
                    "preserved" if any(s not in R for s in support.get(m, [])) else "tainted"
# (3) ids outside desc keep ok   (4) no quarantined output
```

Notes: sweep-to-fixpoint instead of the engine's topological order — same fixpoint (monotone), different
code path; the oracle must not read `taint_parent`, `by`, `integrity`, DB statuses, or engine helpers.
`kind`/`conf` only gate legality, never status. The driver contract per op:
`revoke(x)` → `R ∪= {x}`; `reinstate(x)` → `R −= {x}`; `corroborate(m,s)` → assert map unchanged, add
edge to pending support (R2); after revoke/reinstate: fold pending support, compare **all** statuses,
`check_invariants == []`, assertion `no quarantined`, and `revoked statuses == R`. Structural add-ons
(recommended): tainted ⇒ `taint_parent ∈ parents` and its final status ∈ {revoked, tainted}; ok ⇒
`taint_parent` NULL; preserved ⇒ ≥1 support source ∉ R.

## 4. Hypothesis strategy (honest design)

- Placement: `tests/oracle.py` (pure) + `tests/unit/test_p012_oracle.py` (hand cases) +
  `tests/integration/test_reinstate_oracle.py` (DB property test). Verify the `tests.oracle` import works
  under `python -m pytest` from the repo root; the repo already relies on CWD imports (`evals.*`,
  `src.pedigree.*`); if it does not, fall back to a `tests/__init__.py`-free importlib loader.
- DAG: 2–6 designated roots (≥2; force ≥1 ancestor–descendant root pair), ≤25 nodes (1–4 Sources,
  3–12 Memories, 0–4 Actions); each memory/action draws 0–2 parents from **earlier-created** nodes
  (creation order ⇒ acyclic; no cycle strategy needed); roots include Memory descendants of other roots
  (the 22/150 class). Bias: ~40% of examples nest one root under another.
- Ops: length 3–10; targets: designated roots 80% / any eligible node 20%; mix revoke 40% / reinstate 35%
  / corroborate 25%; include revoke-of-tainted, reinstate-of-never-revoked, repeat revoke.
- Settings: `max_examples=300`, `deadline=None` (real DB I/O; justified), `suppress_health_check=
  [HealthCheck.too_slow]`; no wall-clock assertions. Global pytest timeout is 300 s and F5 gives
  ~0.15–0.4 s/example: mark the test `slow` (protect `make check` ≈10 s), add `@pytest.mark.timeout(900)`,
  and record command + measured wall time in `docs/qa/P-012.md`. `make test`/CI runs it.
- Determinism: explicit `@example` FIRST for the audit repro and for every shrunk counterexample found;
  keep strategy primitives (lists of tuples) so hypothesis shrinks to a printable DAG + op list. Do not
  quote the 300-example sweep as a sampled estimate — it is a property search, no CI/proportion applies;
  if `derandomize=True` is used for CI stability, say so and list the explicit examples.
- Failure output (assert message): full nodes+edges, op list, **first diverging op index**, expected vs
  actual maps (dict diff), DB statuses of every node at that op; also failing `check_invariants` text
  with the op index. Never `assert x == y` without this context.
- Isolation/flakiness: one unique tenant per example (`p012`+uuid4; `ensure_schema`; graph dropped in
  `finally`) — F5 shows ≈35 ms, so per-example isolation is affordable and makes shared-state flakes
  impossible; no parallel assumptions, no retries (a failure is a real divergence), `deadline=None` for
  latency spikes. Unit-test the oracle itself on hand cases first: preserved frontier keeps children ok;
  revoked support is weak; nested roots; non-root revoked; no quarantine output; empty R ⇒ all ok.

## 5. Sensitivity and the mutation procedure

Would this catch the 22/150 class? Yes by construction: (a) the explicit `@example` is the exact audit
repro; (b) any generated sequence containing revoke(X), revoke(descendant Y), reinstate(X) diverges in the
full-map comparison at the reinstate step; with ≥2 roots, forced ancestor pairs, 300 examples × 3–10 ops,
that pattern is overwhelmingly represented — but this must be **demonstrated**, not asserted, by the
mutation run below. What it can still miss: concurrent ingest/quarantine races (P-024; no writer here);
`taint_parent`/counts metadata unless the structural add-ons are included; bugs masked by a shared
misreading of the docs (why R1/R2/R8 matter); longer sequences, >6 roots, >25 nodes, multi-process.

Mutation (evidence in `docs/qa/P-012.md`; scratch worktree; never committed):
1. Save the P-012 diff; in the worktree reverse **exactly** the hunk that stops the clobber — e.g. remove
   the `WHERE n.status <> 'revoked'` guard from the new `Q_REINSTATE_RESET`, or restore the old
   unconditional `Q_REINSTATE_RESET` + `if roots:` skip. Record the exact file:line reverted.
2. `pytest tests/integration/test_reinstate_oracle.py -q -m slow` → RED: the repro test (B `ok` where
   `revoked` expected) and the property test (first diverging step); `check_invariants` on the produced
   graph must report the new marker violation.
3. Restore, re-run → GREEN. Paste commands + raw output + the reverted line. A summary line is not
   evidence (FIX_PROMPT §0).
Also required: a negative invariant test that hand-corrupts a healthy graph (`SET B.status='ok'` after
revoke A/B) and asserts `check_invariants` flags it — proves the invariant catches the corruption
independently of the engine code path.

## 6. The invariant extension — concrete, not prose (FIX_PROMPT line 71)

- **I-a (new):** `MATCH (n:Node) WHERE n.revoked_at IS NOT NULL AND n.status <> 'revoked' RETURN count(n)`
  == 0. Verified: **1** on the broken state (B), 0 expected on the fixed state; legitimate reinstate
  clears the marker (F2/R5). This is the check that catches "a node is `ok` while being a revoked root".
- **I-b (exists):** `Q_INV_OK_HAS_NO_BAD_PARENT` catches the `Cc=ok` half of any partial fix.
- **I-c (exists):** preserved must have ≥1 healthy (status `ok`) corroborating source.
The plan's literal wording — "no node is `ok`/`preserved` … having a revoked ancestor lacking trusted
support" — must NOT be implemented as written: (i) `preserved` with a revoked ancestor is *correct*
behaviour (that is the feature); (ii) a transitive ancestor walk is redundant once I-a+I-b+I-c hold on a
DAG (topological induction: any badness reaching an `ok` node implies a direct bad parent); (iii)
"trusted" is the wrong word (R3). If the team prefers the row-based check
(`MATCH (v:Revocation), (n {id:v.root_id}) WHERE n.status<>'revoked'`), it only works if reinstate also
retires/deletes its row — otherwise it false-positives on the reinstated root (verified F2: count 2).
Prefer I-a and keep rows as history (domain.md §4.3).

## 7. Required changes (minimum for the plan to be sufficient)

1. **Before writing the oracle**, fix the spec it is written from: `docs/01` §6.3 + F-03 reinstate
   semantics (R1), corroboration timing (R2), "healthy support" wording (R3); DECISIONS entry.
2. Implement I-a as above with its negative test, and keep I-b/I-c; do not implement the literal
   "ancestor lacking trusted support" prose.
3. Encode the op-comparison contract in the driver (corroborate ⇒ unchanged map; fold at next recompute)
   and the per-op cross-check `revoked statuses == R`; include the structural `taint_parent` checks.
4. Run the named mutation procedure and paste raw red/green evidence in `docs/qa/P-012.md` (plus the
   negative invariant test).
5. Test budget: mark the sweep `slow` + `@pytest.mark.timeout(900)`, per-example unique tenant + cleanup,
   `deadline=None`, record wall time; explicit `@example` for the repro/shrunk cases.
6. Reconcile with the two existing independent oracles (R8): one global API or a drift-guard test, plus a
   meta-test that `tests/oracle.py` imports nothing from `pedigree` (mechanical enforcement of "no shared
   code with `engine/compute.py`").

With 1–6, the acceptance (300+ green, repro green, mutation red) is **sufficient** for this fix: the
sequence/full-map design is the right instrument, and the mutation run is the right sensitivity evidence.
Without 1–3 the test can be red on correct code (lazy corroboration) or green on the bug (oracle written
from a doc sentence that describes it), which would make the acceptance worthless.

**Verdict: NOT YET.** (The plan's structure is correct; the semantics pinning, invariant formalisation and
comparison contract are missing. Re-review after `docs/fixes/P-012.md` states 1–6; no re-run of the full
review should be needed then.)

Notes: consult directory numbering `008-*` is used twice (`008-opencode-capture`, `008-p012-reinstate`) —
merge into `decision.md` under one 008 series if that was unintended. Any number quoted about this work
("N examples", 22/150) must be produced by the committed test run itself, not copied from AUDIT.md.
