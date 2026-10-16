"""Statistics helpers: seed-cluster ratio and mean percentile bootstraps for E1/E2,
plus Wilson helpers for independent proportions. Stdlib only; deterministic given the seed.
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
    if min(values) == max(values):
        return (mean, mean, mean)
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(iters):
        sample = rng.choices(values, k=n)
        means.append(sum(sample) / n)
    means.sort()
    lo = means[max(0, int(0.025 * iters))]
    hi = means[min(iters - 1, int(0.975 * iters))]
    return (mean, lo, hi)


def cluster_ratio_ci(strata: list[list[tuple[int, int]]], iters: int = 10000,
                     seed: int = 0) -> tuple[float | None, float | None, float | None]:
    """Pooled ratio with percentile seed-cluster bootstrap, conditional on fixed strata.

    Resample whole independent DAGs within each grid cell, including zero-denominator
    DAGs. A degenerate empirical bootstrap is not evidence of certainty. Replicates
    with no denominator are undefined and omitted; all-undefined returns nulls.
    """
    strata = [group for group in strata if group]
    numerator = sum(k for group in strata for k, _ in group)
    denominator = sum(n for group in strata for _, n in group)
    if not denominator:
        return None, None, None
    ratios = {k / n for group in strata for k, n in group if n}
    if len(ratios) == 1:
        value = numerator / denominator
        return value, value, value
    rng = random.Random(seed)
    draws = []
    fixed_k = fixed_n = 0
    varying = []
    for group in strata:
        if len(set(group)) == 1:
            fixed_k += group[0][0] * len(group)
            fixed_n += group[0][1] * len(group)
        else:
            varying.append(group)
    if not varying:
        value = numerator / denominator
        return value, value, value
    for _ in range(iters):
        k, n = fixed_k, fixed_n
        for group in varying:
            sample = rng.choices(group, k=len(group))
            k += sum(pair[0] for pair in sample)
            n += sum(pair[1] for pair in sample)
        if n:
            draws.append(k / n)
    draws.sort()
    return (numerator / denominator, draws[int(0.025 * len(draws))],
            draws[min(len(draws) - 1, int(0.975 * len(draws)))])


def metric_interval(value, lo, hi, *, n_clusters, n_items, n_total, method, source):
    """Publication metadata keeps independent sampling units separate from item counts."""
    return {"value": round(value, 4) if value is not None else None,
            "ci95": [round(lo, 4), round(hi, 4)] if lo is not None else None,
            "n": n_clusters, "n_clusters": n_clusters, "n_items": n_items,
            "n_clusters_total": n_total, "ci_method": method,
            "ci_scope": "conditional on the finite generator grid; degenerate bootstrap is not certainty",
            "source": source}


def proportion_ci(k: int, n: int) -> tuple[float, float, float]:
    """Proportion with a Wilson interval: (p, lo, hi)."""
    lo, hi = wilson(k, n)
    return (k / n if n else 0.0, lo, hi)


def summarise(samples: list[float], seed: int = 0) -> dict:
    mean, lo, hi = mean_ci(samples, seed=seed)
    n = len(samples)
    return {"n": n, "mean": round(mean, 6), "lo": round(lo, 6), "hi": round(hi, 6)}
