"""Pure distribution helpers (percentiles / histogram / threshold counts) — TASK-081.

No numpy dependency here: these are exact, deterministic, and trivially unit-tested
so the report's distribution claims are reproducible from first principles.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile (``q`` in [0, 100]); matches numpy's default.

    Empty input → 0.0 (a degenerate corpus has no distribution; callers report n=0
    alongside, so 0.0 is an honest placeholder rather than a raised error).
    """
    if not values:
        return 0.0
    if not 0.0 <= q <= 100.0:
        raise ValueError(f"percentile q must be in [0, 100], got {q}")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (q / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return float(ordered[low] * (1.0 - frac) + ordered[high] * frac)


@dataclass(frozen=True)
class DistributionSummary:
    """Count + key percentiles + min/max/mean of a value series (for the report)."""

    count: int
    minimum: float
    p50: float
    p90: float
    p95: float
    p99: float
    maximum: float
    mean: float


def summarize(values: Sequence[float]) -> DistributionSummary:
    """Compute the standard distribution summary used throughout the baseline report."""
    if not values:
        return DistributionSummary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    return DistributionSummary(
        count=len(values),
        minimum=float(min(values)),
        p50=percentile(values, 50),
        p90=percentile(values, 90),
        p95=percentile(values, 95),
        p99=percentile(values, 99),
        maximum=float(max(values)),
        mean=float(sum(values) / len(values)),
    )


def count_at_or_above(values: Sequence[float], threshold: float) -> int:
    """How many values are >= `threshold` (clusters that would cross an alert bar)."""
    return sum(1 for v in values if v >= threshold)


def histogram(values: Sequence[float], edges: Sequence[float]) -> list[int]:
    """Bucket counts for half-open bins ``[edges[i], edges[i+1])`` + a final ``[last, ∞)``.

    `edges` must be sorted ascending with >= 2 entries. Returns ``len(edges)`` counts:
    one per bin between consecutive edges, plus one overflow bin at/above the last edge.
    """
    if len(edges) < 2:
        raise ValueError("histogram needs at least 2 edges")
    if any(edges[i] >= edges[i + 1] for i in range(len(edges) - 1)):
        raise ValueError("histogram edges must be strictly ascending")
    counts = [0] * len(edges)
    for value in values:
        placed = False
        for i in range(len(edges) - 1):
            if edges[i] <= value < edges[i + 1]:
                counts[i] += 1
                placed = True
                break
        if not placed and value >= edges[-1]:
            counts[-1] += 1
    return counts
