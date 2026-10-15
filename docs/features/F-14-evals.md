# F-14 - Eval harness: generator, independent oracle, baselines, E1/E2, NUMBERS pipeline

Status: spec | Tests: to be written (failing first) | QA: pending
Implements `docs/03-EVAL-AND-DEMO.md` sections 3-6 and acceptance test AT2.6.

## Behaviour

`evals/gen.py` - deterministic seeded generator (stdlib `random`, no numpy):
- Parameters `S` sources, `M` memories in `L` levels, fan-in `f` (1..4), `p_corr` (probability a
  memory has an independent corroborating source), `A` actions relying on 1..5 memories with 20%
  irreversible. Every node carries a synthetic text drawn from a fixed word pool (B0 needs it).
- The bad source is chosen uniformly among sources with >= 1 descendant.
- Output: a `Dag` (pure model: ids, parents, support, relied_on, irreversible, texts, creation
  order) plus a FalkorDB writer used only by the cross-check test.

`evals/oracle.py` - **independent** ground truth: the docs/01 §6.3 recurrence as a brute-force
fixpoint that sweeps every node until nothing changes (no topological order, different code from
`engine/compute.py`). Returns `{G (should taint), should_preserve, ok, A (affected actions)}`.

`evals/baselines.py` - six systems, each a documented emulation (docs/03 §2):
`B0` TF-IDF cosine delete (theta calibrated on disjoint seeds, sweep reported) | `B1`
first-provenance deletion | `B2` flat 1-hop | `B4` full cascade without support check | `B5`
time-travel rewind (recall 1.0 by construction) | `P` Pedigree = the engine's real `compute_final`
on the same structures the engine reads from the graph.

`evals/stats.py` - `wilson(k, n)` proportions and `bootstrap_ci(values, iters=10000, seed)` means;
every reported number is `mean ± 95% CI` with n recorded.

`evals/run_e1.py` - grid over `L in {2,4,6}`, `f in {1,3}`, `p_corr in {0,0.1,0.3}` with
`S=20, M=200, A=40` and N >= 30 seeds per cell (`--quick`: 2 seeds, one cell). Writes
`evals/results/e1_semantics.csv` (one row per cell x system) and `e1_samples.csv` (per seed), each
file carrying machine info (CPU, RAM, OS, FalkorDB module version, python, commit sha, seed list).
Metrics per docs/03 §3: `recall`, `residual`, `over_invalidation`, `precision`, `F1`,
`action_recall`, `irreversible_recall`, `preserved_correct`.

`evals/run_all.py` - `make eval` / `make eval-quick`; runs E1, regenerates
`evals/results/numbers.json`, calls `scripts/extract_numbers.py` (which writes the
`<!-- NUMBERS:BEGIN -->` block of `docs/NUMBERS.md`) and rewrites `evals/REPORT.md` with the
generated tables plus the docs/03 §7 limitations. Exit non-zero if any check fails.

## No-mock guarantee

E1 compares semantics in-process using the engine's real `compute_final`; the same path is
cross-checked against the **real FalkorDB revoke engine** for a handful of generated DAGs in
`tests/evals/test_eval_pipeline_agreement.py` (write graph -> `revoke()` -> read statuses -> same
sets), so the in-process shortcut is proven equivalent rather than assumed.

## Acceptance tests (write first)
- `tests/evals/test_oracle_agreement.py`: 1000 random small DAGs - oracle == `compute_final`
  exactly (status per node), including cycles rejected by both.
- `tests/evals/test_eval_pipeline_agreement.py`: in-process P == real FalkorDB `revoke` statuses
  on 5 generated DAGs (one per grid shape), including the preserved set and the action set.
- `tests/evals/test_baselines.py`: B5 recall == 1.0 by construction; B2 == direct children only;
  B1 keeps shared/derived items; B4 preserves nothing; B0 sweep is monotone-ish and calibrated on
  disjoint seeds (assert the calibration seeds never appear in the evaluation seeds).
- `tests/evals/test_stats.py`: Wilson on known counts (0/N, N/N, half), bootstrap determinism with
  a fixed seed and width shrink as n grows.

## Evidence needed
- `make eval` exit 0 with CSVs + `evals/REPORT.md`; `docs/NUMBERS.md` block regenerated;
  `make check` still green; eval-statistician review of the design before any big run.
