# NUMBERS - the only allowed source of numbers in README, blog and video

Every measurement printed in README.md, docs/BLOG-DRAFT.md and the demo video script
must appear below, with the script that produced it. `make check` enforces this via
`scripts/check_numbers.py`; `scripts/extract_numbers.py` appends eval results (once
`make eval` exists, F-14). Unflattering values are kept - never rounded away.

<!-- NUMBERS:BEGIN -->
e1_action_recall_b0 = 0.5607   # evals/run_e1.py
e1_action_recall_b1 = 0.4194   # evals/run_e1.py
e1_action_recall_b2 = 0.2258   # evals/run_e1.py
e1_action_recall_b4 = 1.0   # evals/run_e1.py
e1_action_recall_b5 = 1.0   # evals/run_e1.py
e1_action_recall_p = 1.0   # evals/run_e1.py
e1_b0_theta = 0.475   # evals/run_e1.py (calibration)
e1_grid_cells = 18   # evals
e1_irreversible_recall_b0 = 0.5423   # evals/run_e1.py
e1_irreversible_recall_b1 = 0.4136   # evals/run_e1.py
e1_irreversible_recall_b2 = 0.2231   # evals/run_e1.py
e1_irreversible_recall_b4 = 1.0   # evals/run_e1.py
e1_irreversible_recall_b5 = 1.0   # evals/run_e1.py
e1_irreversible_recall_p = 1.0   # evals/run_e1.py
e1_machine = Windows-11-10.0.26300-SP0; Intel64 Family 6 Model 191 Stepping 2, GenuineIntel; 15.7 GB RAM; python 3.12.15; falkor 42201; commit 3941d85   # evals/machineinfo.py
e1_over_invalidation_b0 = 0.0334   # evals/run_e1.py
e1_over_invalidation_b1 = 0.0181   # evals/run_e1.py
e1_over_invalidation_b2 = 0.0036   # evals/run_e1.py
e1_over_invalidation_b4 = 0.0493   # evals/run_e1.py
e1_over_invalidation_b4_deepest_cell = 0.2777   # evals/run_e1.py (cell L6-f3-p0.3)
e1_over_invalidation_b5 = 0.9557   # evals/run_e1.py
e1_over_invalidation_p = 0.0   # evals/run_e1.py
e1_preserved_correct_b0 = 0.0   # evals/run_e1.py
e1_preserved_correct_b1 = 0.0   # evals/run_e1.py
e1_preserved_correct_b2 = 0.0   # evals/run_e1.py
e1_preserved_correct_b4 = 0.0   # evals/run_e1.py
e1_preserved_correct_b5 = 0.0   # evals/run_e1.py
e1_preserved_correct_p = 1.0   # evals/run_e1.py
e1_recall_b0 = 0.4714   # evals/run_e1.py
e1_recall_b1 = 0.3546   # evals/run_e1.py
e1_recall_b2 = 0.1862   # evals/run_e1.py
e1_recall_b2_deepest_cell = 0.2374   # evals/run_e1.py (cell L6-f3-p0.3)
e1_recall_b4 = 1.0   # evals/run_e1.py
e1_recall_b5 = 1.0   # evals/run_e1.py
e1_recall_p = 1.0   # evals/run_e1.py
e1_seeds_per_cell = 30   # evals
e1_systems = 6   # evals
e2_exact_leakage = 0.0   # evals/run_e2.py
e2_leakage_edge_drop_10pct = 0.2412   # evals/run_e2.py
e2_leakage_edge_drop_1pct = 0.012   # evals/run_e2.py
e2_leakage_edge_drop_2pct = 0.0434   # evals/run_e2.py
e2_leakage_edge_drop_5pct = 0.1414   # evals/run_e2.py
e2_window_extra_actions_k10 = 3.3551   # evals/run_e2.py
e2_window_extra_actions_k100 = 3.3747   # evals/run_e2.py
e2_window_extra_actions_k25 = 3.3747   # evals/run_e2.py
e2_window_extra_actions_k5 = 3.2771   # evals/run_e2.py
e2_window_extra_actions_k50 = 3.3747   # evals/run_e2.py
e2_window_over_flag_k10 = 5.4526   # evals/run_e2.py
e2_window_over_flag_k100 = 5.7193   # evals/run_e2.py
e2_window_over_flag_k25 = 5.7193   # evals/run_e2.py
e2_window_over_flag_k5 = 4.4628   # evals/run_e2.py
e2_window_over_flag_k50 = 5.7193   # evals/run_e2.py
e4_blame_p50_n2460 = 5.44   # evals/run_e4.py (2460 nodes)
e4_blame_p50_n820 = 5.4   # evals/run_e4.py (820 nodes)
e4_blame_p50_n8200 = 6.18   # evals/run_e4.py (8200 nodes)
e4_build_n2460 = 4091.9   # evals/run_e4.py (2460 nodes)
e4_build_n820 = 1324.3   # evals/run_e4.py (820 nodes)
e4_build_n8200 = 15264.6   # evals/run_e4.py (8200 nodes)
e4_gate_p50_n2460 = 2.42   # evals/run_e4.py (2460 nodes)
e4_gate_p50_n820 = 2.29   # evals/run_e4.py (820 nodes)
e4_gate_p50_n8200 = 2.82   # evals/run_e4.py (8200 nodes)
e4_impact_p50_n2460 = 16.85   # evals/run_e4.py (2460 nodes)
e4_impact_p50_n820 = 14.22   # evals/run_e4.py (820 nodes)
e4_impact_p50_n8200 = 16.85   # evals/run_e4.py (8200 nodes)
e4_machine = Windows-11-10.0.26300-SP0   # evals/machineinfo.py
e4_revoke_real_p50_n2460 = 318.76   # evals/run_e4.py (2460 nodes)
e4_revoke_real_p50_n820 = 123.45   # evals/run_e4.py (820 nodes)
e4_revoke_real_p50_n8200 = 1080.59   # evals/run_e4.py (8200 nodes)
e4_revoke_real_p95_n2460 = 624.49   # evals/run_e4.py (2460 nodes)
e4_revoke_real_p95_n820 = 171.35   # evals/run_e4.py (820 nodes)
e4_revoke_real_p95_n8200 = 1849.42   # evals/run_e4.py (8200 nodes)
e4_rounds = 5   # evals/run_e4.py
e4b_closure_falkor_n16400 = 4.17   # evals/run_e4b_sqlite.py (algo.BFS)
e4b_closure_falkor_n4100 = 2.38   # evals/run_e4b_sqlite.py (algo.BFS)
e4b_closure_falkor_n820 = 1.81   # evals/run_e4b_sqlite.py (algo.BFS)
e4b_closure_ratio_sqlite_over_falkor_largest = 0.115   # evals/run_e4b_sqlite.py (16400 nodes)
e4b_closure_sqlite_n16400 = 0.48   # evals/run_e4b_sqlite.py (stdlib sqlite3)
e4b_closure_sqlite_n4100 = 0.52   # evals/run_e4b_sqlite.py (stdlib sqlite3)
e4b_closure_sqlite_n820 = 0.28   # evals/run_e4b_sqlite.py (stdlib sqlite3)
falkordb_module_version = 42201   # pedigree db status / MODULE LIST on v4.22.1
falkordb_version = 4.22.1   # scripts/fetch-falkordb.sh (pinned)
python_min = 3.11   # pyproject.toml requires-python
tracks_entered = 2   # docs/DECISIONS.md ADR-000
<!-- NUMBERS:END -->

## How to add a number

1. Produce it with a committed script (evals/, scripts/) - never by hand.
2. Add `key = value  # source: script/file, date` inside the block above.
3. Run `make check`.
