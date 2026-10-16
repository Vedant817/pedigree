# F-14 independent statistical review

Date: 2026-10-16. Role: `.opencode/agents/eval-statistician.md`.
Current verdict: **SIGN-OFF for the scoped F-14 synthetic harness and descriptive local benchmarks**,
following the final artifact review below. The initial findings are retained as the audit history.
Initial verdict: **NOT YET**. The synthetic semantics checks pass, but the original publication
pipeline does not justify its uncertainty, preservation, or reproducibility claims. This is a
review of the repository and measured artifacts, not an endorsement of real capture coverage.

## Commands and observed evidence

- `.venv\Scripts\python.exe -m pytest tests/evals/test_stats.py tests/evals/test_oracle_agreement.py -q`
  -> **11 passed in 1.26s**. Includes 1,000 small random DAG comparisons and three real-FalkorDB
  revoke cross-check shapes. The oracle independently sweeps to a fixpoint; it does not call
  `compute_final`. Both implement the specified recurrence, so agreement validates semantics,
  not whether real-world support is independent or captured lineage is complete.
- `.venv\Scripts\python.exe -m pytest tests/evals/test_review_regressions.py -q`
  -> **4 passed in 0.24s**. Checks textual B0 behavior independent of ancestry, calibration
  threshold sweep, calibration/evaluation seed separation, and nested E2 edge drops.
- `.venv\Scripts\python.exe -m pytest tests/integration/test_isolation_concurrency.py tests/security/test_acl_mechanism.py -q -rs`
  -> **3 passed, 1 skipped in 3.21s**. Skip: `PEDIGREE_DB_ACL_SECRET not set (deployment secret)`.
- Bounded inspection of `e1_samples.csv`: **3,240 rows, 18 cells, 540 distinct cell/seed DAGs**.
  Pedigree's valid per-metric seed counts are recall **522**, affected-action recall **488**,
  irreversible recall **364**, explicit preservation sensitivity **299**. Undefined cases must
  remain missing, rather than count as successes or failures.
- Bounded E2 check using generator seed `2000003` and identical edge-draw streams at
  1/2/5/10% drop: **4/7/29/48** edges removed, nested sets confirmed. Sharing a reseeded stream
  across thresholds is correct. This coupling does not prove every output metric is monotone
  in the presence of independent-support semantics.

## Findings and required changes

1. **High: clustered observations presented as independent trials.** Original
   `run_e1.py::_numbers.pooled` and `run_e2.py::_pooled` use Wilson intervals on sums of node
   counts. Nodes share a seeded graph and support paths; they are not independent Bernoulli
   trials. Keep the weighted pooled count-ratio point estimate if desired, but bootstrap whole
   seed/DAG clusters. For the fixed E1 grid, resample seeds separately within each cell, keeping
   the fixed cell mixture. For E2, resample seeds. State `n_items`, valid `n_clusters`, and total
   seeds separately; distinguish count-weighted pooled ratios from macro means. Use deterministic
   10,000-resample intervals and label them conditional on the synthetic fixed grid and calibrated
   theta. They do not include calibration uncertainty or generalize to arbitrary workloads.

2. **High: publication state corrupted by quick mode and stale artifacts.** Original
   `run_all.py` invokes each quick runner with its default `evals/results` output. E1 overwrites
   `numbers.json` before the final `numbers_quick.json` write; all CSVs can also overwrite full
   results. Isolate every quick output under a separate directory, including intermediate JSON
   and report. Verify byte-for-byte preservation of every full-run publication artifact. At
   review start, `e4b_falkor_vs_sqlite.csv` reported Falkor closure **1.77/2.77 ms**, while
   `REPORT.md` and `NUMBERS.md` still carried older values. Regenerate a coherent full set after
   repairing the pipeline; a successful numbers-token check alone does not establish CSV agreement.

3. **High: computed uncertainty silently discarded.** Original E1/E2 aggregation computes
   `{metric}_lo`/`{metric}_hi`, but CSV writer field lists omit those fields. The report labels
   per-cell tables as bootstrap intervals while displaying means only. Retain bounds and
   metric-specific valid seed counts in CSV and generated tables. E2 should also retain raw
   per-seed samples so aggregate uncertainty is inspectable without an expensive rerun.

4. **Medium: missing values become numerical claims.** `_rate` correctly returns `None`, and
   E2 `_pooled` correctly returns missing values when no data exist. Original E1 pooled metrics
   instead return `value=0.0, ci95=[0.0,0.0], n=0`. Bounded `_numbers([],...)` reproduced this.
   Keep zero-denominator estimates and bounds null; label empty cells as undefined. Neither a
   zero-width interval nor a perfect result on a single synthetic seed proves population safety.

5. **Medium: preservation metric is narrower than its name.** Original `_score` returns
   `preserved_correct=1.0` even when the same should-preserve item is in both `pred` and
   `preserved`. This was reproduced on generated seed `2000003`. Enforce disjoint final status
   sets (or exclude invalidated items), and describe this metric as explicit preservation
   sensitivity. The baselines never assign an explicit preserved status, so their zero is not
   proof that every baseline deletes every supported item. If claiming retention, report the
   fraction of should-preserve items absent from all invalidation/action predictions; if claiming
   preservation safety, report false preservations or preservation precision as well. Synthetic
   corroboration is trusted by the recurrence; adversarial or erroneous support is outside this
   experiment. Graph status preservation is also distinct from a gate authorizing a risky action.

6. **Medium: E4b conclusions must follow the current CSV.** Original `run_all.py::build_report`
   hardcodes “faster at every size measured,” regardless of input data. Derive observed direction
   from current rows, state ties/mixed results, and never assert the same ranking across future
   runs. Original E4b asserts descendant cardinalities only and never validates ancestor results.
   Validate exact ID sets in both directions before calling the queries equivalent. Three timing
   rounds on one generated DAG/root per size give descriptive medians, not a crossover model,
   throughput result, or statistical evidence that a database is universally faster. The graph
   query includes socket overhead and SQLite is in-process memory; state this asymmetry.

7. **Medium: B0 calibration and evaluation optimize different item sets.** Original
   `calibrate_b0_theta` computes F1 on `prediction.pred`, whereas `_score` evaluates
   `prediction.pred | prediction.actions`. At calibration seed `900000`, theta `0.475`, these
   F1 values were **0.243243** versus **0.259740**, with three additionally flagged actions.
   Calibrate against the same item universe used for scoring, then regenerate theta, the
   complete sweep, and evaluation artifacts. Disjoint seeds alone do not fix an objective mismatch.

## Baseline and generator assessment

B0 is an actual smoothed TF-IDF cosine implementation (`baselines.py::_tfidf_vectors`,
`_cosine`, `b0_similarity`), not a lineage heuristic relabeled as vector retrieval. It calibrates
41 thresholds using independent oracle F1 on 24 DAGs with seeds 900000..900023. The 540 default
evaluation seed IDs are disjoint, verified directly. The sweep is emitted. The synthetic text
generator copies parent prefixes and adds noise, so lexical relatedness is deliberately tied to
lineage; this supports a meaningful lexical baseline but is not a claim about embedding memory
products or real paraphrase robustness. Calibration uses the default generator shape, not a
shape-balanced calibration grid; disclose that choice. The threshold is chosen once and must
not be retuned against the published grid.

B1/B2/B4/B5 are emulations of chosen deletion/rewind semantics, not measured competitor products.
B1's first-parent chain rule, B2's one-hop invalidation, B4's support-blind closure, and B5's
creation-order rewind should be described exactly. “Graphiti”, “PACMI”, or similar names do not
establish equivalence to vendor code or paper experiments. P and the oracle share a prescribed
recurrence and all starting nodes are healthy except the revoked root: perfect P scores are
expected under this model, not evidence of detecting malicious sources.

E2 is a model of missing/extra edges. Its window model supplies true parents plus carried reads;
it does not measure actual runtime events or completeness. All generated memories precede the
actions; action buckets reset the synthetic recent-read state. The model's saturation and extra
flags are workload-specific. These numbers cannot establish real session coverage or real benign
gate friction.

## E4b, E5, and E6 publication scope

The existing E4b CSV observed at review start contains **820/4,100 actual nodes**, despite CLI
target labels 1,000/5,000. Descendant closure medians were SQLite **0.31/0.53 ms**, FalkorDB
**1.77/2.77 ms**; ancestor medians SQLite **0.02/0.01 ms**, FalkorDB **0.94/1.39 ms**.
These exact values describe that CSV only and may be replaced by a coherent rerun. They support
the observation that SQLite was faster on those traversal queries in that run. They do not
compare durable graph persistence, the full revoke protocol, capture, authorization, or
tenant-operation semantics. Product architecture reasons for FalkorDB must be stated separately;
SQLite can implement isolation designs, so “SQLite cannot provide isolation” is too broad.

E5 now has a fresh **3 passed, 1 skipped** check here: API isolation matrix, real engine stress
with **20 tenants x 8 writer threads**, and revoke/ingest race invariants. The stress writers call
the engine after schema setup; it is not an HTTP throughput benchmark. ACL mechanism evidence
from an earlier secret-configured run is documented in `docs/qa/F-15.md`; this review's ACL test
was skipped and does not re-prove it. The service's shared DB credentials remain distinct from
deploying per-tenant ACL users. Do not convert API isolation checks into an ACL wiring claim.

E6 remains **blocked by runtime/provider quota** according to the handoff and current progress
record; there are no measured real-trace coverage, canary-recall, or benign-friction estimates
to sign off. State “not run / unavailable, quota blocked,” not “small n” as though an experiment
exists. Synthetic scenario replays and E2 cannot substitute for the requested real recording.

## Verdict

**NOT YET** for publication/sign-off at initial inspection. Fix the clustered intervals,
publication isolation, missing-value handling, preservation interpretation, and data-derived
report claims; then regenerate coherent artifacts and repeat independent bounded checks.
E6 may remain explicitly unmeasured without invalidating a narrowly scoped synthetic E1/E2
and local E4/E4b/E5 report. No large evaluation rerun was performed by this reviewer.

## Second pass: implementation repairs

The builder repaired the seven issues above in source. Independent command
`.venv\Scripts\python.exe -m pytest tests/evals -q` now returns **29 passed in 3.55s**;
`.venv\Scripts\ruff.exe check tests/evals/test_review_regressions.py` returns **All checks passed**.
The added controlled B0-objective regression was first observed failing (the old code chose
theta 1 when the scored-universe optimum was 0), then passed after calibration used the same
action union as E1. Other independent checks confirm cluster-count metadata, null denominators,
retained CSV intervals, exact E4b sets, and isolated quick output routing.

Source/methodology verdict: **PASS for a coherent rerun**, conditional on the stated synthetic
scope and a preservation-sensitivity interpretation. Final publication sign-off still requires
the regenerated CSV/JSON/REPORT/NUMBERS artifacts to agree. Existing unregenerated published
intervals remain the original invalid Wilson intervals until that rerun finishes.

## Final publication review: SIGN-OFF

Reviewed the serialized full-run artifacts generated **2026-10-16 08:54 IST**, engine/eval
commit **3941d85**. The lead reports `evals/run_all.py` exited 0 with no concurrent database
test workload during this final run. This reviewer did not rerun the benchmark or full test suite.

A read-only Python check independently parsed raw CSVs and recomputed count ratios, cluster
counts, denominators and cell means. Observed:

- E1 has **3,240 samples, 540 cell/seed DAGs, 108 cell/system summaries**; E2 has **300 samples,
  30 seeds, 10 condition summaries**. All expected cells have 30 draws per system/condition.
- All **30 E1 pooled headline point estimates** and their valid/total cluster and item counts
  match the sample CSV. The **118 E1/E2 summary rows** retain bounds and metric-specific valid
  counts; their means match the raw samples within CSV rounding tolerance. Undefined metrics
  remain blank. E2 pooled leakage values and cluster/item metadata also match raw samples.
- Every entry in `numbers_e2.json`, `numbers_e4.json`, and `numbers_e4b.json` is present unchanged
  in the merged `numbers.json`. E4b CSV timings agree with that JSON and the generated report.
  The report identifies seed-cluster intervals and warns that degenerate empirical intervals
  do not establish certainty. B0 theta remains **0.475** after recalibration against the corrected
  scoring objective; remaining unchanged is an observed result, not a reason to skip recalibration.
- Final E4b actual node counts are **820 / 4,100 / 16,400**. Closure SQLite/Falkor medians are
  **0.28/1.81**, **0.52/2.38**, **0.48/4.17 ms** respectively. Ancestor SQLite/Falkor medians are
  **0.02/0.86**, **0.01/1.37**, **0.02/3.26 ms**. These are the final CSV's descriptive results,
  replacing the earlier values retained in the initial-review section above.
- `.venv\Scripts\python.exe scripts/check_numbers.py` ->
  **PASS: 2 file(s) checked against 68 allowed values**. The generated report and docs/03 now
  explicitly define preservation-status sensitivity and distinguish it from retention/precision.

**SIGN-OFF** applies to the corrected seeded synthetic E1/E2 methodology and its generated
artifacts, authored API replay description, and descriptive local E4/E4b measurements. It is
conditional on the fixed generator grid, chosen calibration model and observed workload, not a
population safety guarantee. The E5 statement remains scoped to the tested API/engine isolation
and race checks, with the ACL-secret skip and shared administrative credential limitation explicit.

E6/E3b remain **NOT MEASURED**. Since the initial review, the installed OpenCode recheck captured
one genuine read-tool hook payload shape (`docs/consults/opencode-recheck-2026-10-16.md`); its final
response timed out. This changes the evidence from wholly quota-blocked to one payload-shape
observation, and supplies no labeled capture coverage, benign-friction estimate, completed runtime
adapter, or real agent demo. The final generated report states that boundary correctly. No
synthetic substitution or recorded-session result is signed off.

## Final wording check: E2 extra-to-true ratios

Read-only inspection of `README.md`, `docs/BLOG-DRAFT.md`,
`docs/submission/SUBMISSION.md`, and `docs/03-EVAL-AND-DEMO.md` confirms the corrected
description agrees with `run_e2.py::_score`: `over_flag_ratio = |pred - G| / |G|` and
`extra_actions = |flagged_actions - A| / |A|`. The numerators exclude correctly flagged
items/actions. The published **4.4628-5.7193** item and roughly **3.3** action values therefore
describe extra-to-true ratios, not total flagged-to-true ratios. JSON records these as
seed-mean bootstrap estimates; they are model-specific averages, not real-session friction.
The four wording corrections are **PASS** and do not change the scoped sign-off above.
