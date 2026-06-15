"""Unit tests for eval.forward_split — leak-free chronological split + Cheng labels (B2).

Every case is hand-computed so the harness's split boundaries and labels are
reproducible from first principles. The two leakage invariants are asserted directly:
(1) the boundary gap drops birth-time stragglers; (2) a partition's labels depend only
on that partition's cohort references.
"""

from __future__ import annotations

import math

import pytest

from eval.forward_split import (
    ClusterOutcome,
    CohortPolicy,
    ForwardSplitError,
    LabelKind,
    Partition,
    SplitRatios,
    doubling_threshold,
    label_partition,
    label_partitions,
    split_by_time,
    top_quartile_threshold,
)


def _c(cluster_id: int, t0: float, outcome: float, age: int = 3600) -> ClusterOutcome:
    return ClusterOutcome(
        cluster_id=cluster_id,
        t0_epoch=t0,
        final_outcome=outcome,
        age_at_outcome_seconds=age,
    )


# --- ClusterOutcome validation -------------------------------------------------------


@pytest.mark.unit
def test_outcome_rejects_negative_final() -> None:
    with pytest.raises(ForwardSplitError):
        _c(1, 0.0, -1.0)


@pytest.mark.unit
def test_outcome_rejects_nonfinite_t0() -> None:
    with pytest.raises(ForwardSplitError):
        _c(1, math.inf, 1.0)


@pytest.mark.unit
def test_outcome_rejects_negative_age() -> None:
    with pytest.raises(ForwardSplitError):
        _c(1, 0.0, 1.0, age=-1)


# --- SplitRatios validation ----------------------------------------------------------


@pytest.mark.unit
def test_ratios_must_sum_to_one() -> None:
    with pytest.raises(ForwardSplitError):
        SplitRatios(train=0.5, val=0.2, test=0.2)


@pytest.mark.unit
def test_ratios_reject_negative_gap() -> None:
    with pytest.raises(ForwardSplitError):
        SplitRatios(gap_seconds=-1)


# --- chronological split -------------------------------------------------------------


@pytest.mark.unit
def test_split_is_chronological_by_index() -> None:
    # 10 clusters born at t = 0,1,...,9 ; 60/20/20 → 6 train / 2 val / 2 test
    clusters = [_c(i, float(i), 1.0) for i in range(10)]
    split = split_by_time(clusters, ratios=SplitRatios(0.6, 0.2, 0.2))
    assert [c.cluster_id for c in split.train] == [0, 1, 2, 3, 4, 5]
    assert [c.cluster_id for c in split.val] == [6, 7]
    assert [c.cluster_id for c in split.test] == [8, 9]
    assert split.dropped_in_gap == ()


@pytest.mark.unit
def test_split_orders_unsorted_input_and_breaks_ties_by_id() -> None:
    clusters = [_c(2, 5.0, 1.0), _c(1, 5.0, 1.0), _c(0, 1.0, 1.0)]
    split = split_by_time(clusters, ratios=SplitRatios(1.0, 0.0, 0.0))
    assert [c.cluster_id for c in split.train] == [0, 1, 2]


@pytest.mark.unit
def test_split_empty_input() -> None:
    split = split_by_time([], ratios=SplitRatios())
    assert split.train == () and split.val == () and split.test == ()


@pytest.mark.unit
def test_gap_drops_on_both_sides_of_boundary() -> None:
    # Birth times spaced 100s apart so a small gap isolates exactly the boundary-
    # adjacent clusters. n=10, 60/20/20 → n_train=6, n_val=2:
    #   train->val boundary t0 = ordered[6].t0 = 600
    #   val->test  boundary t0 = ordered[8].t0 = 800
    # gap=50 → band [550,650] around 600 drops train tail t0=600? no train idx<6 max
    # t0=500 (not in band); BUT the val head idx6 (t0=600) IS in the band → dropped.
    # band [750,850] around 800 drops val idx7 (t0=700? no) — idx7 t0=700 not in band;
    # test idx8 (t0=800) IS in band → dropped.
    clusters = [_c(i, float(i * 100), 1.0) for i in range(10)]
    split = split_by_time(clusters, ratios=SplitRatios(0.6, 0.2, 0.2, gap_seconds=50))
    dropped_ids = {c.cluster_id for c in split.dropped_in_gap}
    # downstream HEADS at each boundary are dropped (the CRITICAL fix): idx6 (val head)
    # and idx8 (test head) sit exactly on a boundary timestamp.
    assert 6 in dropped_ids
    assert 8 in dropped_ids
    # surviving train is fully separated from the boundary
    assert [c.cluster_id for c in split.train] == [0, 1, 2, 3, 4, 5]


@pytest.mark.unit
def test_gap_guarantees_separation_between_surviving_partitions() -> None:
    # invariant: after the drop, the LAST surviving train cluster is born >= gap before
    # the FIRST surviving test cluster (no train future window reaches a test early one).
    clusters = [_c(i, float(i * 10), 1.0) for i in range(100)]
    gap = 100
    split = split_by_time(clusters, ratios=SplitRatios(0.6, 0.2, 0.2, gap_seconds=gap))
    if split.train and split.val:
        assert split.val[0].t0_epoch - split.train[-1].t0_epoch >= gap
    if split.val and split.test:
        assert split.test[0].t0_epoch - split.val[-1].t0_epoch >= gap


@pytest.mark.unit
def test_partition_accessor() -> None:
    clusters = [_c(i, float(i), 1.0) for i in range(10)]
    split = split_by_time(clusters, ratios=SplitRatios(0.6, 0.2, 0.2))
    assert split.partition(Partition.TRAIN) == split.train
    assert split.partition(Partition.VAL) == split.val
    assert split.partition(Partition.TEST) == split.test


# --- thresholds ----------------------------------------------------------------------


@pytest.mark.unit
def test_doubling_threshold_is_median() -> None:
    assert doubling_threshold([1.0, 2.0, 3.0]) == pytest.approx(2.0)


@pytest.mark.unit
def test_top_quartile_threshold() -> None:
    # 75th percentile of 1..5 (linear interp) = 4.0
    assert top_quartile_threshold([1.0, 2.0, 3.0, 4.0, 5.0]) == pytest.approx(4.0)


@pytest.mark.unit
def test_empty_cohort_threshold_is_zero() -> None:
    assert doubling_threshold([]) == 0.0
    assert top_quartile_threshold([]) == 0.0


# --- labels --------------------------------------------------------------------------


@pytest.mark.unit
def test_doubling_label_balanced_above_median() -> None:
    # outcomes 1,2,3,4,5 ; median 3 ; positive iff > 3 → {4,5}
    clusters = [_c(i, float(i), float(i + 1)) for i in range(5)]
    labels = label_partition(clusters, kind=LabelKind.DOUBLING, cohort=CohortPolicy())
    assert labels == (0.0, 0.0, 0.0, 1.0, 1.0)


@pytest.mark.unit
def test_top_quartile_label() -> None:
    # outcomes 1..5 ; 75th pct = 4 ; positive iff >= 4 → {4,5}
    clusters = [_c(i, float(i), float(i + 1)) for i in range(5)]
    labels = label_partition(clusters, kind=LabelKind.TOP_QUARTILE, cohort=CohortPolicy())
    assert labels == (0.0, 0.0, 0.0, 1.0, 1.0)


@pytest.mark.unit
def test_log_final_regression_target() -> None:
    clusters = [_c(0, 0.0, 0.0), _c(1, 1.0, math.e - 1.0)]
    labels = label_partition(clusters, kind=LabelKind.LOG_FINAL, cohort=CohortPolicy())
    assert labels[0] == pytest.approx(0.0)
    assert labels[1] == pytest.approx(1.0)


@pytest.mark.unit
def test_cohort_median_is_per_age_bucket() -> None:
    # two age cohorts (bucket 100s): young {age 0} outcomes 1,10 ; old {age 200} 2,3.
    # young median 5.5 → only 10 positive ; old median 2.5 → only 3 positive.
    clusters = [
        _c(0, 0.0, 1.0, age=0),
        _c(1, 1.0, 10.0, age=0),
        _c(2, 2.0, 2.0, age=200),
        _c(3, 3.0, 3.0, age=200),
    ]
    labels = label_partition(
        clusters, kind=LabelKind.DOUBLING, cohort=CohortPolicy(bucket_seconds=100)
    )
    assert labels == (0.0, 1.0, 0.0, 1.0)


@pytest.mark.unit
def test_label_partitions_are_independent_no_leakage() -> None:
    # train outcomes are huge, test outcomes tiny. If the test label used the GLOBAL
    # median (leaking train), every test cluster would be negative. Per-partition
    # cohorts keep the test split balanced on its OWN median.
    train = [_c(i, float(i), 1000.0 + i) for i in range(4)]
    test = [_c(10 + i, float(100 + i), float(i + 1)) for i in range(4)]
    split = split_by_time(train + test, ratios=SplitRatios(0.5, 0.0, 0.5))
    labeled = label_partitions(split, kind=LabelKind.DOUBLING, cohort=CohortPolicy())
    # test cohort median over {1,2,3,4} = 2.5 → positives {3,4} → two positives
    assert sum(labeled.test) == 2.0
