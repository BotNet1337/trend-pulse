"""Data-quality gate for offline corpus → clean training subset (TASK-108, B0).

The owner's explicit prerequisite for Track C (ML) is "train only on quality data".
The corpus is pathological (signal-quality report): 68% singletons, three catch-all
mega-buckets (4,102 / 1,713 / 1,210 posts), 5,122 near-duplicate centroid pairs
(cosine >= 0.9), 753 duplicate-topic groups (3,010 clusters / 32%), backfill-shaped,
single-channel-heavy, with recurring "Доброе утро"/daily-market boilerplate chains.
Training a GBDT on this raw would learn artefacts, not virality.

This module defines the GATE that downstream B2 (forward-time-split harness) and C1
(GBDT training) MUST pass clusters through. It is:

- **substrate-agnostic** — `is_quality_cluster()` consumes a `ClusterQualityFeatures`
  record, so it works identically on the prod CSV snapshot (metrics-only) and on the
  re-clustered `corpus.sqlite` stories C-training actually uses. Both substrates
  project into the same record.
- **leak-free** — `ClusterQualityFeatures` carries NO future-label field (no eventual
  engagement / spread). Every feature is EARLY / STRUCTURAL, so the gate runs at
  feature time without leaking the label it will later predict.
- **pure & immutable** — frozen dataclasses; functions return new data, never mutate.
- **transparent** — `assess_cluster()` returns which named gates a cluster failed, so
  the report can break the rejections down per gate and the thresholds stay tunable.

It REUSES the existing `eval/` building blocks (sizes via `clustering_audit`, cosine
duplication via `count_duplicate_centroid_pairs`, percentile/summary via
`distribution`) rather than reimplementing them; the *predicate* itself is the new
piece — no `is_quality_cluster` / co-channel / boilerplate filter existed before.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from eval.corpus import PostRecord

# --- named time constants (CONVENTIONS: time in seconds, no magic literals) ----------

_SECONDS_PER_HOUR = 3600
_SECONDS_PER_DAY = 24 * _SECONDS_PER_HOUR


class QualityInputError(ValueError):
    """A quality-feature record was malformed (out-of-range / negative)."""


@dataclass(frozen=True)
class QualityThresholds:
    """Tunable, named gate thresholds — no magic literals leak into the predicate.

    Defaults are derived from the signal-quality report's pathologies:
    - `min_posts` excludes singletons (68% of the corpus) and near-singletons.
    - `max_posts` excludes the catch-all mega-buckets (lowest in prod = 1,210).
    - `min_channels` excludes single-channel clusters (no cross-channel spread → not
      the product's target signal and label-leakage-prone).
    - `duplicate_cosine` mirrors `clustering_audit.DUPLICATE_CENTROID_COSINE` (0.9).
    - `recurring_*` flag long-span / low-breadth daily boilerplate chains.
    - `max_top_channel_share` flags single-channel-dominated (self-amplified) clusters.
    - `max_fetch_lag_seconds` rejects the backfill fingerprint (fetched long after post).
    """

    min_posts: int = 3
    max_posts: int = 1000
    min_channels: int = 2
    duplicate_cosine: float = 0.9
    recurring_span_seconds: int = 14 * _SECONDS_PER_DAY
    recurring_max_channels: int = 3
    max_top_channel_share: float = 0.9
    max_fetch_lag_seconds: float = 7 * _SECONDS_PER_DAY


@dataclass(frozen=True)
class ClusterQualityFeatures:
    """Substrate-agnostic, leak-free structural features of one cluster.

    Validated at construction (CONVENTIONS: never trust external data). Carries no
    future-label field by design — the gate runs at feature time.
    """

    cluster_id: int
    post_count: int
    unique_channels: int
    span_seconds: int
    max_cross_cluster_cosine: float
    top_channel_share: float
    completeness_ok: bool
    max_fetch_lag_seconds: float

    def __post_init__(self) -> None:
        if self.post_count < 0:
            raise QualityInputError(f"post_count must be >= 0, got {self.post_count}")
        if self.unique_channels < 0:
            raise QualityInputError(f"unique_channels must be >= 0, got {self.unique_channels}")
        if self.span_seconds < 0:
            raise QualityInputError(f"span_seconds must be >= 0, got {self.span_seconds}")
        if not 0.0 <= self.max_cross_cluster_cosine <= 1.0:
            raise QualityInputError(
                f"max_cross_cluster_cosine must be in [0,1], got {self.max_cross_cluster_cosine}"
            )
        if not 0.0 <= self.top_channel_share <= 1.0:
            raise QualityInputError(
                f"top_channel_share must be in [0,1], got {self.top_channel_share}"
            )
        if self.max_fetch_lag_seconds < 0:
            raise QualityInputError(
                f"max_fetch_lag_seconds must be >= 0, got {self.max_fetch_lag_seconds}"
            )


@dataclass(frozen=True)
class QualityVerdict:
    """The gate's decision for one cluster + WHICH named gates it failed (for the report)."""

    cluster_id: int
    is_quality: bool
    failed_gates: tuple[str, ...]


def assess_cluster(
    features: ClusterQualityFeatures, *, thresholds: QualityThresholds
) -> QualityVerdict:
    """Run every named gate; a cluster is quality iff it fails none.

    Each gate is independent and additive — all failures are recorded so the report
    can attribute rejections per gate. The co-channel-dominance gate is only meaningful
    once a cluster spans >= `min_channels` (a single-channel cluster is already rejected
    by the `single_channel` gate), so it is guarded to avoid double-counting singletons.
    """
    failed: list[str] = []

    if features.post_count < thresholds.min_posts:
        failed.append("too_small")
    if features.post_count > thresholds.max_posts:
        failed.append("mega_bucket")
    if features.unique_channels < thresholds.min_channels:
        failed.append("single_channel")
    if features.max_cross_cluster_cosine >= thresholds.duplicate_cosine:
        failed.append("near_duplicate")
    if _is_recurring_boilerplate(features, thresholds):
        failed.append("recurring_boilerplate")
    if (
        features.unique_channels >= thresholds.min_channels
        and features.top_channel_share > thresholds.max_top_channel_share
    ):
        failed.append("co_channel_dominated")
    if not features.completeness_ok:
        failed.append("incomplete")
    if features.max_fetch_lag_seconds > thresholds.max_fetch_lag_seconds:
        failed.append("temporally_insane")

    return QualityVerdict(
        cluster_id=features.cluster_id,
        is_quality=not failed,
        failed_gates=tuple(failed),
    )


def _is_recurring_boilerplate(
    features: ClusterQualityFeatures, thresholds: QualityThresholds
) -> bool:
    """A cluster that persists over a very long span with little channel breadth is a
    recurring boilerplate chain (daily-market / "Доброе утро" posts the harness span
    guard kills), NOT a single spreading story. Zero-span clusters never trip this.
    """
    return (
        features.span_seconds > thresholds.recurring_span_seconds
        and features.unique_channels <= thresholds.recurring_max_channels
    )


def is_quality_cluster(features: ClusterQualityFeatures, *, thresholds: QualityThresholds) -> bool:
    """The downstream GATE: True iff the cluster survives every quality gate.

    C-training (C1) and the forward-time-split harness (B2) call this to build the
    clean training subset — they consume only clusters for which this returns True.
    """
    return assess_cluster(features, thresholds=thresholds).is_quality


@dataclass(frozen=True)
class QualitySummary:
    """Corpus-level roll-up: how many clusters are quality + per-gate failure histogram."""

    total: int
    quality_count: int
    quality_pct: float
    gate_failures: dict[str, int] = field(default_factory=dict)


def summarize_quality(verdicts: Sequence[QualityVerdict]) -> QualitySummary:
    """Aggregate verdicts into corpus totals + a per-gate failure histogram.

    Empty input → total=0, quality_pct=0.0 (honest placeholder, mirrors
    `distribution.summarize`). The histogram counts each gate a cluster failed (a
    cluster failing N gates contributes to N buckets), so the per-gate counts attribute
    the pathologies independently.
    """
    total = len(verdicts)
    if total == 0:
        return QualitySummary(total=0, quality_count=0, quality_pct=0.0, gate_failures={})
    quality_count = sum(1 for v in verdicts if v.is_quality)
    gate_failures: Counter[str] = Counter()
    for verdict in verdicts:
        gate_failures.update(verdict.failed_gates)
    return QualitySummary(
        total=total,
        quality_count=quality_count,
        quality_pct=quality_count / total * 100.0,
        gate_failures=dict(gate_failures),
    )


def build_cluster_features(
    *,
    cluster_id: int,
    posts: Sequence[PostRecord],
    max_cross_cluster_cosine: float,
    max_fetch_lag_seconds: float,
    completeness_ok: bool = True,
) -> ClusterQualityFeatures:
    """Project a cluster's `PostRecord`s into `ClusterQualityFeatures`.

    `max_cross_cluster_cosine` and `max_fetch_lag_seconds` are computed by the caller
    (the cosine pass over centroids is corpus-wide and lives in `clustering_audit`;
    fetch lag needs `fetched_at`, absent from `PostRecord` — passed in). An empty
    cluster yields `post_count=0` (caught by the `too_small` gate). A single-post or
    zero-span cluster yields `span_seconds=0` without dividing by zero. Dominance is a
    RATIO (top channel's post share), so it is breadth-relative, not an absolute count.
    """
    post_count = len(posts)
    if post_count == 0:
        return ClusterQualityFeatures(
            cluster_id=cluster_id,
            post_count=0,
            unique_channels=0,
            span_seconds=0,
            max_cross_cluster_cosine=max_cross_cluster_cosine,
            top_channel_share=0.0,
            completeness_ok=completeness_ok,
            max_fetch_lag_seconds=max_fetch_lag_seconds,
        )

    channel_counts: Counter[int] = Counter(p.channel_id for p in posts)
    unique_channels = len(channel_counts)
    top_channel_share = max(channel_counts.values()) / post_count
    timestamps = [p.posted_at for p in posts]
    span_seconds = int((max(timestamps) - min(timestamps)).total_seconds())

    return ClusterQualityFeatures(
        cluster_id=cluster_id,
        post_count=post_count,
        unique_channels=unique_channels,
        span_seconds=span_seconds,
        max_cross_cluster_cosine=max_cross_cluster_cosine,
        top_channel_share=top_channel_share,
        completeness_ok=completeness_ok,
        max_fetch_lag_seconds=max_fetch_lag_seconds,
    )
