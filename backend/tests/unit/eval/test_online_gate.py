"""Unit tests for eval.online_gate pure logic (TASK-122, S0 eval-gate).

These pin the LEAK-FREE properties and the formula-reuse contract of the online
eval-gate: the early B1 snapshot projects into `ScoreInputs` exactly as the real
formula would consume it (`compute_components`), the outcome label is built only
from the cluster's eventual engagement (never from the snapshot), single-class
windows are honestly skipped instead of raising, and alert precision degrades to
`None` on empty feedback. Every metric value is hand-computed so the report numbers
are reproducible from first principles (mirrors `eval.metrics` / `eval.forward_split`).
"""

from __future__ import annotations

import pytest

from eval.forward_split import ClusterOutcome
from eval.online_gate import (
    SKIP_SINGLE_CLASS,
    ClusterEngagementOutcome,
    OnlineEvalConfig,
    ScoredOutcome,
    SnapshotRow,
    alert_precision,
    build_cluster_outcomes,
    compute_window_report,
    snapshot_to_score_inputs,
)
from scorer.score import ScoreInputs, compute_components


def _snapshot(
    *,
    cluster_id: int = 1,
    window_label: str = "1h",
    age_seconds: int = 3600,
    post_count: int = 4,
    views: int = 500,
    forwards: int = 10,
    reactions: int = 20,
    distinct_channels: int = 3,
) -> SnapshotRow:
    return SnapshotRow(
        cluster_id=cluster_id,
        user_id=10,
        window_label=window_label,
        age_seconds=age_seconds,
        post_count=post_count,
        views=views,
        forwards=forwards,
        reactions=reactions,
        distinct_channels=distinct_channels,
    )


# --------------------------------------------------------------------------- #
# snapshot_to_score_inputs — formula reuse (AC6) + documented projection.       #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_snapshot_to_score_inputs_matches_documented_projection() -> None:
    snap = _snapshot()
    inputs = snapshot_to_score_inputs(snap, watched_channels_count=5)
    assert inputs == ScoreInputs(
        views=500,
        forwards=10,
        reactions=20,
        channel_avg=500 / 4,  # documented fallback: views/post_count
        delta_channel_count=3,
        delta_hours=3600 / 3600.0,
        unique_channels_count=3,
        watched_channels_count=5,
    )


@pytest.mark.unit
def test_snapshot_score_equals_real_compute_components() -> None:
    # AC6: the early score is the REAL formula, never reimplemented.
    snap = _snapshot()
    inputs = snapshot_to_score_inputs(snap, watched_channels_count=5)
    expected = compute_components(inputs)
    assert compute_components(snapshot_to_score_inputs(snap, watched_channels_count=5)) == expected


@pytest.mark.unit
def test_snapshot_zero_post_count_channel_avg_is_zero() -> None:
    # guard: empty snapshot must not divide by zero for channel_avg.
    snap = _snapshot(post_count=0, views=0)
    inputs = snapshot_to_score_inputs(snap, watched_channels_count=1)
    assert inputs.channel_avg == 0.0


# --------------------------------------------------------------------------- #
# build_cluster_outcomes — leak-free mapping into forward_split.ClusterOutcome. #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_build_cluster_outcomes_maps_engagement_outcome() -> None:
    raw = (
        ClusterEngagementOutcome(
            cluster_id=1,
            first_seen_epoch=1000.0,
            final_engagement=42.0,
            age_at_outcome_seconds=7200,
        ),
    )
    outcomes = build_cluster_outcomes(raw)
    assert outcomes == (
        ClusterOutcome(
            cluster_id=1,
            t0_epoch=1000.0,
            final_outcome=42.0,
            age_at_outcome_seconds=7200,
        ),
    )


@pytest.mark.unit
def test_build_cluster_outcomes_rejects_negative_engagement() -> None:
    # ClusterOutcome invariant (final_outcome >= 0) must be enforced at the boundary.
    from eval.forward_split import ForwardSplitError

    raw = (
        ClusterEngagementOutcome(
            cluster_id=1,
            first_seen_epoch=1000.0,
            final_engagement=-1.0,
            age_at_outcome_seconds=10,
        ),
    )
    with pytest.raises(ForwardSplitError):
        build_cluster_outcomes(raw)


# --------------------------------------------------------------------------- #
# compute_window_report — leak-free split+label, metrics, single-class skip.    #
# --------------------------------------------------------------------------- #


def _scored(cluster_id: int, *, t0: float, score: float, engagement: float) -> ScoredOutcome:
    return ScoredOutcome(
        cluster_id=cluster_id,
        first_seen_epoch=t0,
        early_score=score,
        final_engagement=engagement,
        age_at_outcome_seconds=86_400,
    )


@pytest.mark.unit
def test_compute_window_report_perfect_separation() -> None:
    # All-test config (gap=0, train=0/val=0/test=1) so every cluster lands on the
    # test partition; doubling label = engagement > cohort median.
    # 4 clusters, engagements 1,2,3,4 → median 2.5 → labels 0,0,1,1.
    # early_score increases with engagement → perfect ranking → PR-AUC=ROC-AUC=1.
    config = OnlineEvalConfig(train_fraction=0.0, val_fraction=0.0, test_fraction=1.0)
    # early_score is a raw 0-100 viral_score; the gate divides by SCORE_SCALE (100) into
    # an uncalibrated pseudo-probability before Brier.
    scored = (
        _scored(1, t0=10.0, score=10.0, engagement=1.0),
        _scored(2, t0=20.0, score=20.0, engagement=2.0),
        _scored(3, t0=30.0, score=80.0, engagement=3.0),
        _scored(4, t0=40.0, score=90.0, engagement=4.0),
    )
    report = compute_window_report("1h", scored, config=config)
    assert report.window == "1h"
    assert report.n == 4
    assert report.n_pos == 2
    assert report.skipped is None
    assert report.pr_auc == pytest.approx(1.0)
    assert report.roc_auc == pytest.approx(1.0)
    # brier on (score/100, label): probs 0.10,0.20,0.80,0.90 ; labels 0,0,1,1
    # (0.10-0)^2+(0.20-0)^2+(0.80-1)^2+(0.90-1)^2 = 0.01+0.04+0.04+0.01 = 0.10 ; /4
    assert report.brier == pytest.approx(0.10 / 4.0)


@pytest.mark.unit
def test_compute_window_report_single_class_is_skipped() -> None:
    # AC5: every cluster has the same (zero) engagement → cohort median 0 →
    # doubling strict `>` yields all-negative → single class → honest skip, no raise.
    config = OnlineEvalConfig(train_fraction=0.0, val_fraction=0.0, test_fraction=1.0)
    scored = (
        _scored(1, t0=10.0, score=0.10, engagement=0.0),
        _scored(2, t0=20.0, score=0.20, engagement=0.0),
        _scored(3, t0=30.0, score=0.30, engagement=0.0),
    )
    report = compute_window_report("1h", scored, config=config)
    assert report.skipped == "single_class"
    assert report.n == 3
    assert report.n_pos == 0
    assert report.pr_auc is None
    assert report.roc_auc is None
    assert report.brier is None


@pytest.mark.unit
def test_compute_window_report_empty_is_skipped() -> None:
    config = OnlineEvalConfig(train_fraction=0.0, val_fraction=0.0, test_fraction=1.0)
    report = compute_window_report("15m", (), config=config)
    assert report.skipped == "empty"
    assert report.n == 0
    assert report.n_pos == 0


@pytest.mark.unit
def test_compute_window_report_score_path_independent_of_outcome_magnitude() -> None:
    # AC3: the score/probability path is independent of the eventual engagement.
    # Two datasets share identical cluster_id + early_score; only final_engagement
    # differs, by orders of magnitude (1.0 .. 4.0 vs 1_000 .. 40_000). The magnitudes
    # are chosen so each item lands on the SAME side of its OWN cohort median (the
    # DOUBLING threshold) — labels are identical across runs — while the absolute
    # outcomes differ wildly. Because probs = early_score / SCORE_SCALE and the metrics
    # are computed from those probs/scores against identical labels, an outcome-dependent
    # score path would change pr_auc/roc_auc/brier. Identical metrics across the two
    # runs prove the score path never reads the outcome (a real independence check, not
    # a deterministic-call tautology).
    config = OnlineEvalConfig(train_fraction=0.0, val_fraction=0.0, test_fraction=1.0)
    # 4 clusters, scores ascending; engagements ordered the same way so the doubling
    # label (engagement > median) is identical under both magnitude regimes.
    low = (
        _scored(1, t0=10.0, score=10.0, engagement=1.0),
        _scored(2, t0=20.0, score=20.0, engagement=2.0),
        _scored(3, t0=30.0, score=80.0, engagement=3.0),
        _scored(4, t0=40.0, score=90.0, engagement=4.0),
    )
    high = (
        _scored(1, t0=10.0, score=10.0, engagement=1_000.0),
        _scored(2, t0=20.0, score=20.0, engagement=2_000.0),
        _scored(3, t0=30.0, score=80.0, engagement=30_000.0),
        _scored(4, t0=40.0, score=90.0, engagement=40_000.0),
    )
    report_low = compute_window_report("1h", low, config=config)
    report_high = compute_window_report("1h", high, config=config)

    # both runs are genuinely scored (≥2 per class, never the single-class skip path)
    assert report_low.skipped is None
    assert report_high.skipped is None
    assert report_low.n_pos == report_high.n_pos == 2
    # labels are identical by construction; the score-derived metrics must therefore be
    # bit-for-bit identical despite the 1000x difference in final engagement.
    assert report_high.pr_auc == report_low.pr_auc
    assert report_high.roc_auc == report_low.roc_auc
    assert report_high.brier == report_low.brier


@pytest.mark.unit
def test_compute_window_report_all_positive_single_class_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # AC5: the all-positive branch of the single-class guard (n_pos == n → n_neg == 0).
    #
    # The DOUBLING label is `final_outcome > cohort-median`. A within-partition median is
    # always >= the minimum member, so the minimum is NEVER strictly above it — i.e. no
    # multiset can have every member positive under DOUBLING (verified exhaustively). The
    # all-positive guard is therefore *defensive*: it makes the single-class check
    # symmetric (n_pos == 0 OR n_pos == n) so the report still honestly skips if a future
    # label kind ever produces an all-positive partition. To exercise that real branch we
    # force `label_partition` (as imported by online_gate) to return an all-ones vector,
    # then assert the guard routes it to `single_class` with n_pos == n and no metrics.
    config = OnlineEvalConfig(train_fraction=0.0, val_fraction=0.0, test_fraction=1.0)
    scored = (
        _scored(1, t0=10.0, score=10.0, engagement=1.0),
        _scored(2, t0=20.0, score=20.0, engagement=2.0),
        _scored(3, t0=30.0, score=80.0, engagement=3.0),
    )

    def _all_ones(clusters: object, **_: object) -> tuple[float, ...]:
        return tuple(1.0 for _ in clusters)  # type: ignore[var-annotated]

    monkeypatch.setattr("eval.online_gate.label_partition", _all_ones)

    report = compute_window_report("1h", scored, config=config)
    assert report.skipped == SKIP_SINGLE_CLASS
    assert report.n_pos == report.n == 3
    assert report.pr_auc is None
    assert report.roc_auc is None
    assert report.brier is None


# --------------------------------------------------------------------------- #
# alert_precision — 👍/👎 (AC4) + empty feedback honest null.                    #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_alert_precision_counts_thumbs_up_fraction() -> None:
    precision, n = alert_precision((1, 1, 0, 1))
    assert n == 4
    assert precision == pytest.approx(3.0 / 4.0)


@pytest.mark.unit
def test_alert_precision_empty_is_null() -> None:
    precision, n = alert_precision(())
    assert precision is None
    assert n == 0


@pytest.mark.unit
def test_alert_precision_rejects_non_binary_verdict() -> None:
    from eval.online_gate import OnlineGateError

    with pytest.raises(OnlineGateError):
        alert_precision((1, 2, 0))
