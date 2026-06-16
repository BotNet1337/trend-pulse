"""Online eval-gate: leak-free quality of the v2 score on the live TG B1 stream (TASK-122).

S0 of the scoring-evolution plan. This is the PURE core of a reproducible offline job
that puts an HONEST quality number on the production v2 formula — the baseline S3/S4
are judged against — by joining each cluster's EARLY B1 feature snapshot (15m/30m/1h
after first-seen) to its EVENTUAL engagement outcome, with no information from the
future leaking into the early score or a comparable cluster's label.

What it does, all on typed records (DB I/O lives in `scripts/eval_gate.py`, never here):

1. project a B1 `cluster_feature_snapshots` row into the real `scorer.score.ScoreInputs`
   and compute the EARLY score via `compute_components` — the formula is NEVER
   reimplemented here (the single source stays `scorer/score.py`);
2. build the cluster's eventual engagement outcome into a `forward_split.ClusterOutcome`
   (`final_outcome` = cumulative weighted engagement, measured over the WHOLE cluster,
   which is strictly later than the early window → leak-free);
3. per window, run the leak-free `split_by_time` + `label_partition` (Cheng balanced
   DOUBLING label, cohort-median computed WITHIN the test partition) and report
   PR-AUC / ROC-AUC / Brier (score÷100 as an uncalibrated pseudo-probability) on the
   test partition; single-class / empty windows are honestly skipped, never scored;
4. compute alert precision = fraction of 👍 among rated alerts (`None` on empty feedback).

Everything is pure, immutable (frozen dataclasses), numpy-free and unit-tested so the
report is reproducible from first principles (mirrors `eval.metrics` /
`eval.forward_split` / `eval.scoring_replay`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from eval.forward_split import (
    ClusterOutcome,
    CohortPolicy,
    LabelKind,
    SplitRatios,
    label_partition,
    split_by_time,
)
from eval.metrics import average_precision, brier_score, roc_auc
from scorer.feature_snapshots import OBSERVATION_WINDOW_SECONDS
from scorer.score import SCORE_SCALE, ScoreInputs

# Seconds → hours for the velocity delta (mirrors scorer.tasks._SECONDS_PER_HOUR /
# scoring_replay._SECONDS_PER_HOUR — same named quantum, kept local so the pure module
# has no import-time dependency on a task-module private constant).
_SECONDS_PER_HOUR = 3600.0

# Default watched-channel count when no live watchlist exists offline — mirrors
# `FormulaFallbackModel.watched_channels_count` default (1). Documented CLI assumption:
# cross_channel is reported under this explicit count.
DEFAULT_WATCHED_CHANNELS_COUNT = 1

# Verdict integers for alert feedback (👍/👎). Named, not magic literals — mirror
# `storage.models.alert_feedback.VERDICT_UP / VERDICT_DOWN` (kept local to keep this
# pure module free of a storage import).
_VERDICT_UP = 1
_VERDICT_DOWN = 0

# Honest skip reasons surfaced in the report instead of raising on a degenerate window.
SKIP_EMPTY = "empty"
SKIP_SINGLE_CLASS = "single_class"


class OnlineGateError(ValueError):
    """An online-gate input was malformed (bad verdict, etc.) — fail fast at the boundary."""


@dataclass(frozen=True)
class OnlineEvalConfig:
    """Knobs for the eval-gate run — all defaults are documented, no magic literals.

    - ``watched_channels_count`` cross-channel denominator (no live watchlist offline;
      default mirrors `FormulaFallbackModel`).
    - ``train_fraction`` / ``val_fraction`` / ``test_fraction`` chronological split (sum
      to 1.0); the gate reports metrics on the TEST partition.
    - ``split_gap_seconds`` no-overlap boundary guard (see `forward_split.SplitRatios`).
    - ``cohort_bucket_seconds`` comparable-age cohort width for the DOUBLING median
      (0 = a single global cohort).
    - ``windows`` the valid early observation windows (defaults to the B1 capture set).
    """

    watched_channels_count: int = DEFAULT_WATCHED_CHANNELS_COUNT
    train_fraction: float = 0.6
    val_fraction: float = 0.2
    test_fraction: float = 0.2
    split_gap_seconds: int = 0
    cohort_bucket_seconds: int = 0
    windows: tuple[str, ...] = field(default_factory=lambda: tuple(OBSERVATION_WINDOW_SECONDS))

    def __post_init__(self) -> None:
        if self.watched_channels_count < 0:
            raise OnlineGateError(
                f"watched_channels_count must be >= 0, got {self.watched_channels_count}"
            )

    @property
    def split_ratios(self) -> SplitRatios:
        """The forward-split ratios + boundary gap derived from this config."""
        return SplitRatios(
            train=self.train_fraction,
            val=self.val_fraction,
            test=self.test_fraction,
            gap_seconds=self.split_gap_seconds,
        )

    @property
    def cohort_policy(self) -> CohortPolicy:
        """The comparable-age cohort policy for the DOUBLING label."""
        return CohortPolicy(bucket_seconds=self.cohort_bucket_seconds)


@dataclass(frozen=True)
class SnapshotRow:
    """One B1 `cluster_feature_snapshots` row as the gate sees it (metrics-only, early).

    A faithful, validated mirror of the persisted columns — the EARLY feature side of
    the join. Carries NO outcome/label (B1 is leak-free by construction).
    """

    cluster_id: int
    user_id: int
    window_label: str
    age_seconds: int
    post_count: int
    views: int
    forwards: int
    reactions: int
    distinct_channels: int


@dataclass(frozen=True)
class ClusterEngagementOutcome:
    """A cluster's EVENTUAL engagement outcome — the label-time side of the join.

    - ``final_engagement`` cumulative weighted engagement (views + forwards·F +
      reactions·R) over ALL the cluster's posts, measured strictly later than the early
      window (leak-free). Must be >= 0 (enforced downstream by `ClusterOutcome`).
    - ``age_at_outcome_seconds`` the cluster's lifetime at measurement — the cohort key.
    """

    cluster_id: int
    first_seen_epoch: float
    final_engagement: float
    age_at_outcome_seconds: int


@dataclass(frozen=True)
class ScoredOutcome:
    """One cluster paired up: its EARLY score + its EVENTUAL engagement + split keys.

    The atom `compute_window_report` consumes — the early ``early_score`` is a pure
    function of the cluster's snapshot (computed upstream via `compute_components`), the
    ``final_engagement`` is the leak-free future outcome the label is built from.
    """

    cluster_id: int
    first_seen_epoch: float
    early_score: float
    final_engagement: float
    age_at_outcome_seconds: int


@dataclass(frozen=True)
class WindowReport:
    """Metrics for one observation window on the test partition (or an honest skip).

    ``n`` / ``n_pos`` are ALWAYS reported beside the metrics so a thin / degenerate
    window is transparent. On an empty or single-class window the AUC/Brier are ``None``
    and ``skipped`` carries the reason (the metrics are never computed → never raise).
    """

    window: str
    n: int
    n_pos: int
    pr_auc: float | None
    roc_auc: float | None
    brier: float | None
    skipped: str | None


@dataclass(frozen=True)
class GateReport:
    """The full eval-gate result: per-window metrics + alert precision."""

    windows: tuple[WindowReport, ...]
    alert_precision: float | None
    alert_feedback_n: int


def snapshot_to_score_inputs(snapshot: SnapshotRow, *, watched_channels_count: int) -> ScoreInputs:
    """Project a B1 snapshot into `ScoreInputs` — documented assumptions, formula untouched.

    Mirrors the `eval.scoring_replay` projection: ``views/forwards/reactions`` straight
    from the snapshot; ``delta_channel_count = unique_channels_count = distinct_channels``;
    ``delta_hours = age_seconds / 3600``; ``channel_avg = views / post_count`` (the same
    documented cold-channel fallback proxy — not consumed by the v2 engagement term, kept
    for backwards-compat); ``watched_channels_count`` is the explicit CLI assumption (no
    live watchlist offline). The score itself is computed by the caller via the REAL
    `scorer.score.compute_components` — this function only assembles its input.
    """
    channel_avg = snapshot.views / snapshot.post_count if snapshot.post_count else 0.0
    return ScoreInputs(
        views=snapshot.views,
        forwards=snapshot.forwards,
        reactions=snapshot.reactions,
        channel_avg=channel_avg,
        delta_channel_count=snapshot.distinct_channels,
        delta_hours=snapshot.age_seconds / _SECONDS_PER_HOUR,
        unique_channels_count=snapshot.distinct_channels,
        watched_channels_count=watched_channels_count,
    )


def build_cluster_outcomes(
    outcomes: Sequence[ClusterEngagementOutcome],
) -> tuple[ClusterOutcome, ...]:
    """Map engagement outcomes into leak-free `forward_split.ClusterOutcome` records.

    `ClusterOutcome.__post_init__` validates the invariants (finite birth, non-negative
    finite outcome, non-negative age) at the boundary — a bad outcome raises rather than
    being silently accepted.
    """
    return tuple(
        ClusterOutcome(
            cluster_id=outcome.cluster_id,
            t0_epoch=outcome.first_seen_epoch,
            final_outcome=outcome.final_engagement,
            age_at_outcome_seconds=outcome.age_at_outcome_seconds,
        )
        for outcome in outcomes
    )


def _scored_to_cluster_outcome(item: ScoredOutcome) -> ClusterOutcome:
    """Build a leak-free `forward_split.ClusterOutcome` directly from a `ScoredOutcome`.

    The early ``early_score`` is carried separately (it is the ranking/probability signal,
    NOT part of the outcome); only the leak-free future fields cross into `ClusterOutcome`,
    whose `__post_init__` validates the invariants (finite birth, non-negative finite
    outcome, non-negative age) at the boundary.
    """
    return ClusterOutcome(
        cluster_id=item.cluster_id,
        t0_epoch=item.first_seen_epoch,
        final_outcome=item.final_engagement,
        age_at_outcome_seconds=item.age_at_outcome_seconds,
    )


def compute_window_report(
    window: str,
    scored: Sequence[ScoredOutcome],
    *,
    config: OnlineEvalConfig,
) -> WindowReport:
    """PR-AUC / ROC-AUC / Brier for one window on the leak-free test partition.

    Chronological `split_by_time` (older→train, newer→test) then a per-partition
    Cheng DOUBLING label (cohort-median computed WITHIN the test partition) keeps the
    measurement leak-free. The early score (already computed from the snapshot upstream)
    is used both as the ranking signal (PR-AUC/ROC-AUC) and, normalised score÷SCORE_SCALE
    and clamped to [0, 1], as the uncalibrated pseudo-probability for Brier.

    Empty window → ``skipped="empty"``. A single-class test partition (``n_pos==0`` or
    ``n_neg==0``, e.g. cohort-median 0 on sparse TG) → ``skipped="single_class"`` with
    ``n``/``n_pos`` reported; the AUCs are NOT called (they would raise).
    """
    if not scored:
        return WindowReport(
            window=window, n=0, n_pos=0, pr_auc=None, roc_auc=None, brier=None, skipped=SKIP_EMPTY
        )

    outcomes = tuple(_scored_to_cluster_outcome(item) for item in scored)
    score_by_cluster = {item.cluster_id: item.early_score for item in scored}

    split = split_by_time(outcomes, ratios=config.split_ratios)
    test = split.test
    if not test:
        return WindowReport(
            window=window, n=0, n_pos=0, pr_auc=None, roc_auc=None, brier=None, skipped=SKIP_EMPTY
        )

    labels_float = label_partition(test, kind=LabelKind.DOUBLING, cohort=config.cohort_policy)
    labels = [int(label) for label in labels_float]
    probs = [_score_to_probability(score_by_cluster[cluster.cluster_id]) for cluster in test]
    scores = [score_by_cluster[cluster.cluster_id] for cluster in test]

    n = len(test)
    n_pos = sum(labels)
    if n_pos == 0 or n_pos == n:
        return WindowReport(
            window=window,
            n=n,
            n_pos=n_pos,
            pr_auc=None,
            roc_auc=None,
            brier=None,
            skipped=SKIP_SINGLE_CLASS,
        )

    return WindowReport(
        window=window,
        n=n,
        n_pos=n_pos,
        pr_auc=average_precision(scores, labels),
        roc_auc=roc_auc(scores, labels),
        brier=brier_score(probs, labels),
        skipped=None,
    )


def _score_to_probability(score: float) -> float:
    """Normalise a 0-100 v2 viral_score into an UNCALIBRATED [0, 1] pseudo-probability.

    ``score / SCORE_SCALE`` clamped to [0, 1] — exactly `FormulaFallbackModel.
    predict_proba`'s normalisation. The v2 formula is a ranking signal, NOT a calibrated
    probability; the report flags this Brier as an uncalibrated baseline.
    """
    return min(max(score / SCORE_SCALE, 0.0), 1.0)


def alert_precision(verdicts: Sequence[int]) -> tuple[float | None, int]:
    """Alert precision = fraction of 👍 among rated alerts, or ``(None, 0)`` on no feedback.

    Each verdict is 1 (👍 useful) or 0 (👎 noise); anything else raises (never silently
    drop a bad verdict). Empty feedback → ``(None, 0)`` (honest placeholder — prod may
    have 0 rated alerts; the gate must still run and grow as feedback accrues).
    """
    bad = sorted({v for v in verdicts if v not in (_VERDICT_DOWN, _VERDICT_UP)})
    if bad:
        raise OnlineGateError(f"verdicts must be 0 or 1, found: {bad[:5]}")
    n = len(verdicts)
    if n == 0:
        return None, 0
    up = sum(1 for v in verdicts if v == _VERDICT_UP)
    return up / n, n
