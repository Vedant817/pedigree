# Eval sign-off — independent statistical/honesty review

Date: 2026-10-17. Reviewer: `eval-statistician` subagent (read-only on `src/` and eval code).
HEAD reviewed: `f98c0df`; published artifacts generated at commit `3941d85`
(2026-10-16 08:54 IST). P-022 landed after this review and touches neither `evals/`
nor `docs/NUMBERS.md`.

## Verdict

**NOT SIGNED** — one concrete reproduction-path defect must be fixed first (it makes the
required `make eval` acceptance fail); everything else in the published eval is verified
reproducible and coherent. The numbers themselves are honest; the sign-off is blocked on
the pipeline, not on the results.

Required fix (do not edit eval code from this review): add `opencode_recheck_version`
to `evals/static_numbers.py` (value `"1.19.0"`, source
`docs/consults/opencode-recheck-2026-10-16.md (installed opencode.exe)`), **or** make
`scripts/extract_numbers.py` preserve curated keys. Then re-run the simulation below and
confirm `make eval` exits 0.

## Verifications run (command → observed)

1. **Oracle independence (no shared code with `engine/`)**
   - Read `evals/oracle.py`: imports only `dataclasses`; no pedigree import.
     `evals/baselines.py` imports `pedigree.engine.compute.compute_final` **only for
     system P** (the system under test); all truth comes from
     `evals/oracle.truth_for_dag`. `run_e4.py`/`run_e4b_sqlite.py` import no engine
     status logic. No script reads the metric it is supposed to predict; B0's theta is
     calibrated on disjoint seeds and the sweep is committed.
   - `& .venv\Scripts\python.exe -m pytest tests/evals -q` → **29 passed in 5.00s**
     (includes 1,000-DAG oracle↔`compute_final` agreement and 3 real-FalkorDB revoke
     cross-checks).

2. **Published numbers = committed code (full regeneration, redirected to temp so no
   repo file was touched)**
   - `python -m evals.run_e1 --out <temp>\e1full` → θ **0.4750**, 18 cells × 30 seeds ×
     6 systems, 21.5 s. Diff vs committed CSVs: `e1_samples.csv` 3,240 rows
     **equal=True**; `e1_semantics.csv` 108 rows **equal=True**;
     `e1_b0_theta_sweep.csv` 41 rows **equal=True**; `numbers.json` 36 E1 keys
     **0 diffs** (only `e1_machine` commit sha differs).
   - `python -m evals.run_e2 --out <temp>\e2full` → 300 rows; `e2_samples.csv`
     **equal=True**, `e2_capture.csv` **equal=True**, `numbers_e2.json` **JSON
     equal=True**.
   - Coherence: all E4/E4b CSV values ↔ `numbers_e4.json`/`numbers_e4b.json` ↔ merged
     `numbers.json` **PASS** (E4b ratio 0.115); `evals/REPORT.md` headline table vs
     `numbers.json` **34 rows, 0 mismatches**; REPORT E4 and E4b tables vs CSVs
     **PASS**.

3. **`make eval-quick` spot check** — ran in **15.2 s**, E3 `[e3] PASS`, published
   artifacts byte-identical by SHA-256 **True**; quick artifacts isolated under
   `evals/results/quick/` (untracked).

4. **NUMBERS check** — `python scripts/check_numbers.py` → **PASS: 2 file(s) checked
   against 69 allowed values**; also PASS on
   `README.md docs/BLOG-DRAFT.md docs/submission/SUBMISSION.md docs/WALKTHROUGH.md`
   (5 files). `NUMBERS.md` vs `numbers.json`: **all 83 shared keys match exactly**;
   `NUMBERS.md` has **1 extra key** — `opencode_recheck_version = 1.19.0` (cited in
   `README.md` line 257).

5. **DEFECT (why NOT SIGNED)** — simulated the real pipeline in a temp sandbox:
   `scripts/extract_numbers.py` wrote **83 values** into a copy of `NUMBERS.md`
   (dropping `opencode_recheck_version`, added in `bb9511a` after the last full run
   `b6d9dcd`), then `scripts/check_numbers.py README.md docs/BLOG-DRAFT.md --numbers
   <copy>` → **FAIL: `README.md: '1.19' not in docs/NUMBERS.md`**, exit code 1.
   So a full `make eval` today exits non-zero at its own final `check_numbers` step,
   breaking the E1 acceptance "`make eval` reproduces … `check_numbers` passes". No
   published value is wrong; the regeneration path is.

6. **Baseline fairness / attempted strengthening (all on the full 540-DAG grid)**
   - B0 oracle-tuned upper bound (per-DAG best theta chosen *with ground truth* —
     strictly stronger than any fair engineer): pooled recall **0.781**,
     over-invalidation **0.1198**, action recall **0.860**, irreversible **0.872**,
     mean best F1 0.7202 → even cheating on calibration cannot reach P/B4's recall 1.0.
     Comparison survives.
   - B4 + "subtract supported nodes only": recall 1.0, over-invalidation **0.0378**
     (worse than P's 0.0).
   - B4 + "prune supported nodes and their descendants": recall **0.9245**,
     over-invalidation 0.0, action recall 0.9385, irreversible 0.9347 → leaks when a
     tainted path crosses a preserved branch. P (recall 1.0 **and** over 0.0) strictly
     dominates both stronger variants on all seeds.
   - Honest negatives are disclosed: B4/B5 tie P on recall/action/irreversible recall at
     1.0 (P is not better there); E4b shows SQLite faster than FalkorDB on the raw
     traversal primitive (ratio 0.115); E2 window over-flags 4.4628–5.7193× items /
     ~3.3× actions; revoke p50 123→1081 ms at 820→8200 nodes; E6/E3b **NOT MEASURED**;
     B0–B5 are documented emulations.

## Threats to validity (must remain stated)

- **Synthetic data:** generator with built-in ground truth; E2 is a model of capture
  error; E3 replays patterns; demo is synthetic. Disclosed in docs/03 §7, REPORT,
  README.
- **Oracle shares our semantics:** `evals/oracle.py` is implementation-independent of
  `engine/compute.py` but implements the *same recurrence*; P is perfect (recall 1.0,
  over-invalidation 0.0 on all 540 seeds) **by construction**. Docs/03 §4/§7 and README
  say E1 has built-in ground truth and quantifies semantics, not lineage discovery;
  REPORT should add one explicit sentence to its E1 intro (currently only "independent
  oracle").
- **Single machine:** Windows 11, 24 cores, 15.7 GB RAM, local FalkorDB 4.22.1 (module
  42201), python 3.12.15, commit `3941d85`; E4 n=5 rounds/size, E4b n=3 medians/size —
  descriptive, no crossover model, no cloud, no cross-host variance. Recorded in CSV
  headers and REPORT.
- **Sizes:** FIX_PROMPT asked 1k/10k/100k-node graphs; actual E1 DAGs are ~260 nodes,
  E4/E4b 820/2460/8200 and 820/4100/16400 nodes (requested 1000/3000/10000 and
  1000/5000/20000 in CSV headers). No public 100k claim exists (docs/03 explicitly
  disclaims the million-node target), but REPORT's E4 section should state
  requested-vs-actual; only the CSVs record `requested`.
- Minor/cosmetic: `python evals/run_e1.py` fails without `-m`/`PYTHONPATH` (docstring is
  wrong; `make eval` works); Wilson helpers unused by the publication path; tracked
  `evals/results/numbers_quick.json` is inert; `docs/DEMO_SCRIPT.md` does not exist (no
  video numbers to check yet).

## Remaining tasks

1. Fix `static_numbers.py`/`extract_numbers.py` as above, then re-run the simulation (or
   full `make eval`) and flip the verdict to **SIGNED** (see addendum below).
2. Optional polish (not required for the sign-off): one E1-intro sentence in
   `evals/REPORT.md` about the shared recurrence; requested-vs-actual note in the E4
   section.

## Addendum — defect fixed, acceptance re-run (2026-10-17, same session)

**Verdict flipped to SIGNED.** Required fix applied and verified; `make eval` now
exits 0 end to end.

1. `opencode_recheck_version` (`1.19.0`, source as the published line says) was added
   to `evals/static_numbers.py`, so `run_all.py` merges it into
   `evals/results/numbers.json` before `scripts/extract_numbers.py` rewrites the
   block. The misleading docstring of `extract_numbers.py` ("curated static facts
   already in docs/NUMBERS.md are preserved") now states the real behaviour.
2. New regression test `tests/evals/test_numbers_pipeline.py` pins the invariant that
   broke: every key published in `docs/NUMBERS.md` must exist in
   `evals/results/numbers.json` or in `STATIC_NUMBERS`. `pytest tests/evals -q` →
   **30 passed** (29 + the new test).
3. Acceptance: `make eval` → **exit 0**; its final `scripts/check_numbers.py` step
   passes (`PASS: 2 file(s) checked against 70 allowed values`, was 69);
   `docs/NUMBERS.md` line 90 carries the key.
4. Regenerated artifacts were committed with the fix. E1/E2 rows are identical apart
   from the recorded `commit_sha` (now `495be9b`). E4/E4b are fresh measurements and
   they moved with the engine revision, not only with noise:
   `e4_revoke_real_p50_n820` 123.45 → 51.93 ms, `n2460` 318.76 → 76.92 ms, `n8200`
   1080.59 → 81.22 ms (p95 `n8200` 1849.42 → 141.91 ms), while blame/impact/gate p50s
   are unchanged within a millisecond, and the build phase measured ~1.5–1.6x higher
   (1324.3 → 2049.4 ms at n=820). `engine/revoke.py`, `db/queries.py` and
   `engine/quota.py` all changed after the previous run (see
   `git diff 3941d85..HEAD -- src/pedigree/engine src/pedigree/db`), and every CSV
   header records the machine and commit. `evals/REPORT.md` and `docs/NUMBERS.md`
   were regenerated from this run, so the published tables match their own artifacts;
   `check_numbers` passes against the prose.
5. Found while re-running the suite, fixed separately (P-022 follow-up commit
   `ba41f70`): import-time Prometheus collectors crashed when the package was loaded
   under a second module identity (`tests/evals` imports `src.pedigree...` alongside
   `pedigree...`). `observability._metric` now reuses the registered collector. The
   30-passed result above includes that fix.

The threats to validity and the honest negatives listed above are unchanged; the
optional polish items remain open and are not sign-off blockers.
