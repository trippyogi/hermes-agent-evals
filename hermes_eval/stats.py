"""Small reliability stats. Not a framework. Binary rates get Wilson intervals."""

from __future__ import annotations

import math
import statistics
from typing import Iterable


def summarize_continuous(values: Iterable[float | int | None]) -> dict:
    nums = [float(v) for v in values if isinstance(v, (int, float))]
    n = len(nums)
    if n == 0:
        return {"n": 0, "median": None, "iqr": None, "min": None, "max": None}
    ordered = sorted(nums)
    if n >= 4:
        q1 = statistics.quantiles(ordered, n=4, method="inclusive")[0]
        q3 = statistics.quantiles(ordered, n=4, method="inclusive")[2]
        iqr = round(q3 - q1, 4)
    else:
        iqr = None
    return {
        "n": n,
        "median": round(statistics.median(ordered), 4),
        "iqr": iqr,
        "min": ordered[0],
        "max": ordered[-1],
    }


def wilson_interval(successes: int, n: int, z: float = 1.96) -> dict:
    """95% Wilson score interval for a binomial rate. None if n==0."""
    if n <= 0:
        return {"n": 0, "rate": None, "ci95": None}
    p = successes / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = (z * math.sqrt((p * (1 - p) + z2 / (4 * n)) / n)) / denom
    return {
        "n": n,
        "rate": round(p, 4),
        "ci95": [round(max(0.0, center - half), 4), round(min(1.0, center + half), 4)],
        "method": "wilson",
    }


def pass_at_k(trials: Iterable[bool], k: int | None = None) -> dict:
    """pass@k = succeeds at least once in k; pass^k = succeeds every time."""
    bits = [bool(x) for x in trials]
    n = len(bits) if k is None else min(k, len(bits))
    window = bits[:n]
    if n == 0:
        return {"n": 0, "pass_at_k": None, "pass_hat_k": None}
    return {
        "n": n,
        "pass_at_k": any(window),
        "pass_hat_k": all(window),
    }
