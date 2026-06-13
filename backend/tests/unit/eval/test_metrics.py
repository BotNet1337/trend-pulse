"""Unit tests for eval.metrics pure ranking-quality helpers (TASK-085).

Each metric is checked against a closed-form / hand-computed value so the report's
numbers are reproducible from first principles.
"""

from __future__ import annotations

import pytest

from eval.metrics import (
    MetricInputError,
    confusion_at_threshold,
    precision_at_k,
    roc_auc,
    separation,
    spearman_rho,
)


@pytest.mark.unit
def test_auc_perfect_separation() -> None:
    # every positive scores above every negative -> AUC = 1.0
    scores = [0.1, 0.2, 0.9, 0.8]
    labels = [0, 0, 1, 1]
    assert roc_auc(scores, labels) == pytest.approx(1.0)


@pytest.mark.unit
def test_auc_reversed_is_zero() -> None:
    scores = [0.9, 0.8, 0.1, 0.2]
    labels = [0, 0, 1, 1]
    assert roc_auc(scores, labels) == pytest.approx(0.0)


@pytest.mark.unit
def test_auc_interleaved_known_value() -> None:
    # positives sit at the LOWER scores -> they tend to be out-ranked.
    # pos ranks = 1,3 (rank-sum 4); AUC = (4 - 2*3/2) / (2*2) = 1/4 = 0.25
    scores = [1.0, 2.0, 3.0, 4.0]
    labels = [1, 0, 1, 0]
    assert roc_auc(scores, labels) == pytest.approx(0.25)


@pytest.mark.unit
def test_auc_true_coin_flip_is_half() -> None:
    # symmetric placement (one pos high, one pos low) -> AUC = 0.5
    scores = [4.0, 3.0, 2.0, 1.0]
    labels = [1, 0, 0, 1]
    assert roc_auc(scores, labels) == pytest.approx(0.5)


@pytest.mark.unit
def test_auc_handles_ties() -> None:
    # one pos and one neg tied -> that pair contributes 0.5
    scores = [1.0, 1.0]
    labels = [1, 0]
    assert roc_auc(scores, labels) == pytest.approx(0.5)


@pytest.mark.unit
def test_auc_single_class_raises() -> None:
    with pytest.raises(MetricInputError):
        roc_auc([0.1, 0.2], [1, 1])


@pytest.mark.unit
def test_auc_length_mismatch_raises() -> None:
    with pytest.raises(MetricInputError):
        roc_auc([0.1, 0.2], [1])


@pytest.mark.unit
def test_auc_rejects_non_binary_label() -> None:
    with pytest.raises(MetricInputError):
        roc_auc([0.1, 0.2, 0.3], [0, 1, 2])


@pytest.mark.unit
def test_separation_rejects_non_binary_label() -> None:
    # a stray label of 2 would otherwise be silently dropped from both classes
    with pytest.raises(MetricInputError):
        separation([1.0, 2.0, 3.0], [1, 0, 2])


@pytest.mark.unit
def test_confusion_rejects_non_binary_label() -> None:
    with pytest.raises(MetricInputError):
        confusion_at_threshold([1.0, 2.0], [1, 5], 1.0)


@pytest.mark.unit
def test_precision_at_k_top_hits() -> None:
    scores = [0.9, 0.8, 0.2, 0.1]
    labels = [1, 1, 0, 0]
    assert precision_at_k(scores, labels, 2) == pytest.approx(1.0)
    assert precision_at_k(scores, labels, 4) == pytest.approx(0.5)


@pytest.mark.unit
def test_precision_at_k_clamps_to_size() -> None:
    assert precision_at_k([0.5], [1], 10) == pytest.approx(1.0)


@pytest.mark.unit
def test_precision_at_k_tie_break_is_deterministic() -> None:
    # all tied scores -> top-2 are the first two by original index
    scores = [1.0, 1.0, 1.0]
    labels = [0, 1, 1]
    assert precision_at_k(scores, labels, 2) == pytest.approx(0.5)


@pytest.mark.unit
def test_precision_at_k_rejects_nonpositive_k() -> None:
    with pytest.raises(MetricInputError):
        precision_at_k([0.5], [1], 0)


@pytest.mark.unit
def test_spearman_perfect_positive() -> None:
    scores = [1.0, 2.0, 3.0, 4.0]
    ordinal = [10.0, 20.0, 30.0, 40.0]
    assert spearman_rho(scores, ordinal) == pytest.approx(1.0)


@pytest.mark.unit
def test_spearman_perfect_negative() -> None:
    scores = [1.0, 2.0, 3.0, 4.0]
    ordinal = [40.0, 30.0, 20.0, 10.0]
    assert spearman_rho(scores, ordinal) == pytest.approx(-1.0)


@pytest.mark.unit
def test_spearman_known_value() -> None:
    # rho = 1 - 6*sum(d^2)/(n*(n^2-1)); n=5, rank diffs d = 0,-1,1,-1,1 -> sum d^2 = 4
    # rho = 1 - 6*4/(5*24) = 1 - 24/120 = 0.8
    scores = [1.0, 2.0, 3.0, 4.0, 5.0]
    ordinal = [1.0, 3.0, 2.0, 5.0, 4.0]
    assert spearman_rho(scores, ordinal) == pytest.approx(0.8)


@pytest.mark.unit
def test_spearman_constant_series_raises() -> None:
    with pytest.raises(MetricInputError):
        spearman_rho([1.0, 1.0, 1.0], [1.0, 2.0, 3.0])


@pytest.mark.unit
def test_separation_margins() -> None:
    scores = [10.0, 12.0, 1.0, 2.0, 3.0]
    labels = [1, 1, 0, 0, 0]
    sep = separation(scores, labels)
    assert sep.viral_count == 2
    assert sep.noise_count == 3
    assert sep.viral_mean == pytest.approx(11.0)
    assert sep.noise_mean == pytest.approx(2.0)
    assert sep.mean_margin == pytest.approx(9.0)
    assert sep.viral_median == pytest.approx(11.0)
    assert sep.noise_median == pytest.approx(2.0)
    assert sep.median_margin == pytest.approx(9.0)


@pytest.mark.unit
def test_separation_single_class_raises() -> None:
    with pytest.raises(MetricInputError):
        separation([1.0, 2.0], [1, 1])


@pytest.mark.unit
def test_confusion_counts_and_rates() -> None:
    scores = [9.0, 8.0, 2.0, 1.0]
    labels = [1, 0, 1, 0]
    c = confusion_at_threshold(scores, labels, 5.0)
    # >=5: items 9(pos) and 8(neg) fire
    assert (c.true_positive, c.false_positive, c.true_negative, c.false_negative) == (1, 1, 1, 1)
    assert c.precision == pytest.approx(0.5)
    assert c.recall == pytest.approx(0.5)
    assert c.alerts == 2


@pytest.mark.unit
def test_confusion_no_alerts_precision_zero() -> None:
    c = confusion_at_threshold([1.0, 2.0], [1, 0], 100.0)
    assert c.alerts == 0
    assert c.precision == 0.0
    assert c.recall == 0.0
