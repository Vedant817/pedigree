"""stats.py: Wilson intervals and bootstrap determinism (docs/03 section 3)."""
from __future__ import annotations

from evals.stats import mean_ci, proportion_ci, summarise, wilson


def test_wilson_known_values():
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and hi < 0.3
    lo, hi = wilson(10, 10)
    assert hi > 0.99 and hi <= 1.0 and lo > 0.7
    lo, hi = wilson(5, 10)
    assert 0.2 < lo < 0.5 and 0.5 < hi < 0.8
    assert wilson(0, 0) == (0.0, 0.0)


def test_bootstrap_is_deterministic_and_narrows_with_n():
    values = [float(i % 7) for i in range(40)]
    a = mean_ci(values, iters=2000, seed=3)
    b = mean_ci(values, iters=2000, seed=3)
    assert a == b
    wide = mean_ci(values[:4], iters=2000, seed=3)
    assert (wide[2] - wide[1]) >= (a[2] - a[1])


def test_proportion_and_summary_shapes():
    p, lo, hi = proportion_ci(3, 30)
    assert 0 < lo <= p <= hi < 1
    s = summarise([1.0, 2.0, 3.0], seed=1)
    assert s["n"] == 3 and s["lo"] <= s["mean"] <= s["hi"]
