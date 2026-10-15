"""Statistics helpers for the evals (docs/03 section 3): Wilson intervals for proportions,
percentile bootstrap for means. Stdlib only; deterministic given the seed.
"""
from __future__ import annotations

import math
import random


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """95% Wilson score interval for a proportion (safe at 0 and n)."""
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def mean_ci(values: list[float], iters: int = 10000, seed: int = 0) -> tuple[float, float, float]:
    """Bootstrap 95% CI for the mean. Returns (mean, lo, hi). Deterministic for a fixed seed."""
    if not values:
        return (0.0, 0.0, 0.0)
    mean = sum(values) / len(values)
    if len(values) == 1:
        return (mean, mean, mean)
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(iters):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[max(0, int(0.025 * iters))]
    hi = means[min(iters - 1, int(0.975 * iters))]
    return (mean, lo, hi)


def proportion_ci(k: int, n: int) -> tuple[float, float, float]:
    """Proportion with a Wilson interval: (p, lo, hi)."""
    lo, hi = wilson(k, n)
    return (k / n if n else 0.0, lo, hi)


def summarise(samples: list[float], seed: int = 0) -> dict:
    mean, lo, hi = mean_ci(samples, seed=seed)
    n = len(samples)
    return {"n": n, "mean": round(mean, 6), "lo": round(lo, 6), "hi": round(hi, 6)}
