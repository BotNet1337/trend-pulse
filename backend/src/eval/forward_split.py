"""Forward-time-split + Cheng-style virality labels for the early-detection harness.

TASK-110 (Track B→C / B2). This module is the LEAK-FREE core of the predictive
harness: it turns a set of clusters — each observed only over its first ``T_obs`` of
life (the EARLY window) and carrying a *future* outcome measured over its full life —
into a chronological train/val/test split and a binary virality label, WITHOUT any
information from the future leaking into either the split boundary or a comparable
cluster's label.

Two leakage hazards it closes:

1. **Temporal leakage at the split boundary.** Clusters are split older→train,
   newer→test by birth time (``t0``); a configurable GAP drops every cluster whose
   birth falls inside the boundary band so no train cluster's *future* observation
   window overlaps a test cluster's *early* window. (Cheng et al. WWW'14 §3 split a
   cascade dataset chronologically; the gap is the conservative no-overlap guard.)

2. **Label leakage via the cohort.** The Cheng "doubling" label is balanced by
   construction — a cluster is positive iff its eventual outcome exceeds the MEDIAN
   of *comparable-age* clusters. The cohort median is the label's reference, so it
   MUST be computed within the split partition it labels (never the global/test set),
   which `label_partitions` enforces.

Everything here is pure, immutable, numpy-free and unit-tested so the harness's
labels and split are reproducible from first principles (mirrors `eval.metrics` /
`eval.distribution`). The numpy-driven corpus harness (eval_offline) feeds typed
`ClusterOutcome` records in and consumes the typed split/labels out.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from eval.distribution import percentile


class ForwardSplitError(ValueError):
    """A forward-split / label input was malformed (bad ordering, ratios, empty)."""


@dataclass(frozen=True)
class ClusterOutcome:
    """One cluster as the harness sees it: WHEN it was born, plus its future outcome.

    Validated at construction (never trust external data). The split uses only
    ``t0_epoch`` (birth time) and ``age_at_outcome_seconds`` (how much of the cluster's
    life the ``final_outcome`` summarises); the EARLY feature vector lives separately
    in the harness (this record carries the *label-time* quantities, never features).

    - ``t0_epoch``            cluster birth (first-seen) as a unix timestamp.
    - ``final_outcome``       the future quantity the label is built from (eventual
                              engagement or eventual distinct-channel spread). Must be
                              finite and >= 0 (engagement/spread are non-negative).
    - ``age_at_outcome_seconds`` the cluster's lifetime over which ``final_outcome`` was
                              measured — the cohort key for the comparable-age median.
    """

    cluster_id: int
    t0_epoch: float
    final_outcome: float
    age_at_outcome_seconds: int

    def __post_init__(self) -> None:
        if not math.isfinite(self.t0_epoch):
            raise ForwardSplitError(f"t0_epoch must be finite, got {self.t0_epoch}")
        if not math.isfinite(self.final_outcome) or self.final_outcome < 0:
            raise ForwardSplitError(
                f"final_outcome must be finite and >= 0, got {self.final_outcome}"
            )
        if self.age_at_outcome_seconds < 0:
            raise ForwardSplitError(
                f"age_at_outcome_seconds must be >= 0, got {self.age_at_outcome_seconds}"
            )


class Partition(Enum):
    """Which chronological partition a cluster fell into (or was dropped from)."""

    TRAIN = "train"
    VAL = "val"
    TEST = "test"


@dataclass(frozen=True)
class SplitRatios:
    """Train/val/test fractions (must sum to 1.0) + the boundary gap in seconds.

    ``gap_seconds`` is the no-overlap guard: any cluster whose birth lands within
    ``gap_seconds`` *after* a partition boundary is DROPPED, so a train cluster's
    future window cannot reach into the next partition's early window. A zero gap
    disables the guard (used by tests that want the raw chronological cut).
    """

    train: float = 0.6
    val: float = 0.2
    test: float = 0.2
    gap_seconds: int = 0

    def __post_init__(self) -> None:
        for name, value in (("train", self.train), ("val", self.val), ("test", self.test)):
            if not 0.0 <= value <= 1.0:
                raise ForwardSplitError(f"{name} ratio must be in [0,1], got {value}")
        total = self.train + self.val + self.test
        if abs(total - 1.0) > 1e-9:
            raise ForwardSplitError(f"ratios must sum to 1.0, got {total}")
        if self.gap_seconds < 0:
            raise ForwardSplitError(f"gap_seconds must be >= 0, got {self.gap_seconds}")


@dataclass(frozen=True)
class ForwardSplit:
    """The chronological partition assignment + which clusters the gap dropped."""

    train: tuple[ClusterOutcome, ...]
    val: tuple[ClusterOutcome, ...]
    test: tuple[ClusterOutcome, ...]
    dropped_in_gap: tuple[ClusterOutcome, ...]

    def partition(self, which: Partition) -> tuple[ClusterOutcome, ...]:
        """Typed accessor for one partition (avoids stringly-typed attribute lookup)."""
        if which is Partition.TRAIN:
            return self.train
        if which is Partition.VAL:
            return self.val
        return self.test


def split_by_time(clusters: Sequence[ClusterOutcome], *, ratios: SplitRatios) -> ForwardSplit:
    """Chronological older→train / newer→test split by birth time, with a boundary gap.

    Clusters are ordered ascending by ``t0_epoch`` (ties broken by ``cluster_id`` for
    determinism). The first ``train`` fraction becomes train, the next ``val``
    fraction val, the remainder test — by *index* on the sorted order, so the split is
    stable regardless of timestamp clumping.

    The ``gap_seconds`` guard is a band of that width placed at EACH boundary
    timestamp and drops every cluster whose birth lands within the band on EITHER side
    (the upstream tail AND the downstream head). Dropping only the upstream tail would
    leave a downstream cluster born exactly at the boundary, whose early window is not
    separated from the surviving upstream cluster's future window — so both sides must
    be cleared to make the no-leakage guarantee hold (closes code-review CRITICAL).
    After the drop, the last surviving train cluster is born >= ``gap_seconds`` before
    the first surviving val cluster, and likewise for val→test. Empty input → all
    partitions empty (the harness reports n alongside).
    """
    ordered = sorted(clusters, key=lambda c: (c.t0_epoch, c.cluster_id))
    n = len(ordered)
    if n == 0:
        return ForwardSplit(train=(), val=(), test=(), dropped_in_gap=())

    n_train = int(n * ratios.train)
    n_val = int(n * ratios.val)
    # boundary birth-times (the t0 of the first cluster of the *next* partition)
    train_end_t0 = ordered[n_train].t0_epoch if n_train < n else math.inf
    val_end_t0 = ordered[n_train + n_val].t0_epoch if (n_train + n_val) < n else math.inf
    gap = ratios.gap_seconds

    def in_band(t0: float, boundary: float) -> bool:
        """True iff a positive gap is set and ``t0`` lies within it on either side.

        A zero gap disables the guard entirely (the raw chronological cut), so a
        cluster sitting exactly on a boundary timestamp is NOT dropped when gap == 0.
        """
        if gap <= 0:
            return False
        return boundary - gap <= t0 <= boundary + gap

    train: list[ClusterOutcome] = []
    val: list[ClusterOutcome] = []
    test: list[ClusterOutcome] = []
    dropped: list[ClusterOutcome] = []
    for index, cluster in enumerate(ordered):
        t0 = cluster.t0_epoch
        if index < n_train:
            # train tail: drop if within gap BEFORE the train->val boundary.
            (dropped if in_band(t0, train_end_t0) else train).append(cluster)
        elif index < n_train + n_val:
            # val: drop if within gap of EITHER the train->val or val->test boundary.
            if in_band(t0, train_end_t0) or in_band(t0, val_end_t0):
                dropped.append(cluster)
            else:
                val.append(cluster)
        else:
            # test head: drop if within gap AFTER the val->test boundary.
            (dropped if in_band(t0, val_end_t0) else test).append(cluster)

    return ForwardSplit(
        train=tuple(train),
        val=tuple(val),
        test=tuple(test),
        dropped_in_gap=tuple(dropped),
    )


class LabelKind(Enum):
    """The three virality-label formulations the harness compares."""

    DOUBLING = "doubling"  # Cheng balanced: outcome > cohort median (≈ "doubles")
    TOP_QUARTILE = "top_quartile"  # outcome >= cohort 75th pct (rarer positives)
    LOG_FINAL = "log_final"  # regression target: log1p(final_outcome) (not binary)


@dataclass(frozen=True)
class CohortPolicy:
    """How comparable-age cohorts are formed for the median/quartile reference.

    Clusters are bucketed by ``age_at_outcome_seconds // bucket_seconds`` so the
    "comparable-age" median is taken among clusters of similar lifetime (a 6h-old and a
    6-day-old story are not comparable). ``bucket_seconds <= 0`` means a single global
    cohort (every cluster compared to the whole partition).
    """

    bucket_seconds: int = 0

    def __post_init__(self) -> None:
        if self.bucket_seconds < 0:
            raise ForwardSplitError(f"bucket_seconds must be >= 0, got {self.bucket_seconds}")

    def cohort_key(self, cluster: ClusterOutcome) -> int:
        """Which age-cohort a cluster belongs to (0 = single global cohort)."""
        if self.bucket_seconds <= 0:
            return 0
        return cluster.age_at_outcome_seconds // self.bucket_seconds


def doubling_threshold(outcomes: Sequence[float]) -> float:
    """Cheng balanced-doubling reference = the MEDIAN eventual outcome of the cohort.

    A cluster is positive iff its eventual outcome strictly exceeds this median, which
    makes the label ≈ 50/50 by construction (the balanced "did it spread more than the
    typical comparable cluster" question Cheng et al. WWW'14 use to avoid a degenerate
    rare-positive task). Empty cohort → 0.0 (honest placeholder; the caller reports n).
    """
    if not outcomes:
        return 0.0
    return percentile(list(outcomes), 50)


def top_quartile_threshold(outcomes: Sequence[float]) -> float:
    """Top-quartile reference = the cohort's 75th percentile (rarer, harder positives)."""
    if not outcomes:
        return 0.0
    return percentile(list(outcomes), 75)


def label_partition(
    clusters: Sequence[ClusterOutcome],
    *,
    kind: LabelKind,
    cohort: CohortPolicy,
) -> tuple[float, ...]:
    """Label one partition's clusters, using ONLY that partition's cohort references.

    Computing the median/quartile within the partition being labelled is what keeps the
    label leak-free: a test cluster's label never depends on train outcomes (or the
    other way round). Binary kinds (``DOUBLING`` / ``TOP_QUARTILE``) return 0.0/1.0
    floats so the result is uniform regardless of kind; ``LOG_FINAL`` returns the
    regression target ``log1p(final_outcome)``. Output order matches input order.

    For binary kinds the per-cohort threshold is computed once over the cohort's
    outcomes, then each cluster is compared to its own cohort's threshold.

    KNOWN degeneracy (documented, not silently hidden): on a sparse corpus a cohort
    whose median (DOUBLING) or 75th pct (TOP_QUARTILE) is 0.0 produces all-negative
    labels — the strict ``>`` (DOUBLING) and the ``reference > 0`` guard (TOP_QUARTILE)
    both refuse to call a zero-outcome cluster positive. Such windows surface as a
    single-class partition that the harness detects (``n_pos == 0``) and reports/skips
    rather than scoring a meaningless AUC. TOP_QUARTILE is therefore systematically
    rarer than DOUBLING on sparse data — expected, compared side by side in the report.
    """
    if kind is LabelKind.LOG_FINAL:
        return tuple(math.log1p(c.final_outcome) for c in clusters)

    threshold_fn = doubling_threshold if kind is LabelKind.DOUBLING else top_quartile_threshold
    # group outcomes by cohort, compute each cohort's threshold once
    cohorts: dict[int, list[float]] = {}
    for cluster in clusters:
        cohorts.setdefault(cohort.cohort_key(cluster), []).append(cluster.final_outcome)
    thresholds = {key: threshold_fn(values) for key, values in cohorts.items()}

    labels: list[float] = []
    for cluster in clusters:
        reference = thresholds[cohort.cohort_key(cluster)]
        if kind is LabelKind.DOUBLING:
            labels.append(1.0 if cluster.final_outcome > reference else 0.0)
        else:  # TOP_QUARTILE — inclusive at the 75th pct so the top quartile is positive
            labels.append(1.0 if cluster.final_outcome >= reference and reference > 0 else 0.0)
    return tuple(labels)


@dataclass(frozen=True)
class LabeledPartitions:
    """Binary labels for each partition (parallel to the split's cluster tuples)."""

    train: tuple[float, ...]
    val: tuple[float, ...]
    test: tuple[float, ...]


def label_partitions(
    split: ForwardSplit, *, kind: LabelKind, cohort: CohortPolicy
) -> LabeledPartitions:
    """Label every partition independently (each from its OWN cohort references).

    This is the function the harness calls: it guarantees no cross-partition label
    leakage because `label_partition` is applied per partition in isolation.
    """
    return LabeledPartitions(
        train=label_partition(split.train, kind=kind, cohort=cohort),
        val=label_partition(split.val, kind=kind, cohort=cohort),
        test=label_partition(split.test, kind=kind, cohort=cohort),
    )
