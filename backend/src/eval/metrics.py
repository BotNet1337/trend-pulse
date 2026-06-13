"""Pure ranking-quality metrics for proving the viral_score is MEANINGFUL (TASK-085).

These helpers answer the owner's question — "does a high score genuinely mean
*spreading / worth an alert*, and a low score *noise*?" — with concrete, reproducible
numbers rather than a vibe. They operate on ``(score, label)`` pairs where ``label``
is a binary 1 = viral / 0 = noise (for AUC / precision@k / separation) or an ordinal
rank (for Spearman). They are exact, deterministic, numpy-free, and unit-tested so the
report's claims are reproducible from first principles (mirrors `eval.distribution`).

The score formula itself is NEVER reimplemented here — these are label-vs-score
quality metrics that consume scores produced by the real `scorer.score` module.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from eval.distribution import percentile


class MetricInputError(ValueError):
    """Inputs to a metric were malformed (length mismatch / empty / bad labels)."""


def _check_pairs(scores: Sequence[float], labels: Sequence[float]) -> None:
    """Validate parallel score/label sequences at the boundary (never trust input)."""
    if len(scores) != len(labels):
        raise MetricInputError(
            f"scores and labels must have equal length ({len(scores)} != {len(labels)})"
        )
    if not scores:
        raise MetricInputError("need at least one (score, label) pair")


def _check_binary_labels(labels: Sequence[int]) -> None:
    """Reject any label outside {0, 1} (binary-label metrics silently drop others)."""
    bad = sorted({label for label in labels if label not in (0, 1)})
    if bad:
        raise MetricInputError(f"labels must be 0 or 1, found: {bad[:5]}")


def roc_auc(scores: Sequence[float], labels: Sequence[int]) -> float:
    """ROC-AUC of `scores` ranking the binary `labels` (1 = viral, 0 = noise).

    Computed via the rank-sum (Mann-Whitney U) identity, which is exact and handles
    tied scores correctly by averaging tied ranks::

        AUC = (R_pos - n_pos*(n_pos + 1) / 2) / (n_pos * n_neg)

    where ``R_pos`` is the sum of (1-based, tie-averaged) ranks of the positive
    examples in the ascending-by-score ordering. AUC = 1.0 means every viral item
    outranks every noise item (perfect separation); 0.5 means the score is no better
    than a coin flip; < 0.5 means it ranks them *backwards*.

    Degenerate cases (all-positive or all-negative labels) have no AUC defined and
    raise -- the caller must report n alongside and handle the single-class case.
    """
    _check_pairs(scores, labels)
    _check_binary_labels(labels)
    n_pos = sum(1 for label in labels if label == 1)
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        raise MetricInputError("AUC is undefined when all labels are one class")
    ranks = _tie_averaged_ranks([float(s) for s in scores])
    rank_sum_pos = sum(rank for rank, label in zip(ranks, labels, strict=True) if label == 1)
    return (rank_sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def _tie_averaged_ranks(values: Sequence[float]) -> list[float]:
    """1-based ranks ascending, ties sharing the average of their rank positions."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        # positions i..j (0-based) -> 1-based ranks (i+1)..(j+1); share their average
        avg_rank = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def precision_at_k(scores: Sequence[float], labels: Sequence[int], k: int) -> float:
    """Fraction of the top-`k` items (ranked by score, descending) that are truly viral.

    "If we alerted on the k highest-scoring clusters, how many would be real signals?"
    Ties at the k-th boundary are broken deterministically by original index so the
    result is reproducible. `k` is clamped to the available item count.
    """
    _check_pairs(scores, labels)
    _check_binary_labels(labels)
    if k <= 0:
        raise MetricInputError(f"k must be positive, got {k}")
    k = min(k, len(scores))
    # descending by score; stable tie-break on original index keeps it deterministic
    order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
    top = order[:k]
    hits = sum(1 for i in top if labels[i] == 1)
    return hits / k


def spearman_rho(scores: Sequence[float], ordinal: Sequence[float]) -> float:
    """Spearman rank-correlation between `scores` and an `ordinal` judgement series.

    Uses tie-averaged ranks on both series, then Pearson correlation of the ranks
    (the general definition that is correct under ties). +1 = the score orders items
    exactly like the human ordinal judgement; 0 = unrelated; -1 = reversed. Requires
    >= 2 points and non-constant ranks on each side (else correlation is undefined).
    """
    _check_pairs(scores, ordinal)
    if len(scores) < 2:
        raise MetricInputError("Spearman needs at least 2 points")
    rank_a = _tie_averaged_ranks([float(s) for s in scores])
    rank_b = _tie_averaged_ranks([float(o) for o in ordinal])
    return _pearson(rank_a, rank_b)


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Pearson correlation; raises if either series is constant (zero variance)."""
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        raise MetricInputError("correlation undefined: a series has zero variance")
    return cov / (var_x**0.5 * var_y**0.5)


@dataclass(frozen=True)
class Separation:
    """Score separation between the viral and noise classes (means, medians, margin)."""

    viral_count: int
    noise_count: int
    viral_mean: float
    noise_mean: float
    viral_median: float
    noise_median: float
    mean_margin: float
    median_margin: float


def separation(scores: Sequence[float], labels: Sequence[int]) -> Separation:
    """Mean/median score of viral vs noise items + the margins between them.

    A large positive margin (viral well above noise) is direct evidence the score
    discriminates. Requires at least one item of each class.
    """
    _check_pairs(scores, labels)
    _check_binary_labels(labels)
    viral = [float(s) for s, label in zip(scores, labels, strict=True) if label == 1]
    noise = [float(s) for s, label in zip(scores, labels, strict=True) if label == 0]
    if not viral or not noise:
        raise MetricInputError("separation needs at least one viral and one noise item")
    viral_mean = sum(viral) / len(viral)
    noise_mean = sum(noise) / len(noise)
    viral_median = percentile(viral, 50)
    noise_median = percentile(noise, 50)
    return Separation(
        viral_count=len(viral),
        noise_count=len(noise),
        viral_mean=viral_mean,
        noise_mean=noise_mean,
        viral_median=viral_median,
        noise_median=noise_median,
        mean_margin=viral_mean - noise_mean,
        median_margin=viral_median - noise_median,
    )


@dataclass(frozen=True)
class ConfusionAtThreshold:
    """Confusion-matrix counts + precision/recall at one alert threshold."""

    threshold: float
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    precision: float
    recall: float

    @property
    def alerts(self) -> int:
        """How many items would fire an alert at this threshold (TP + FP)."""
        return self.true_positive + self.false_positive


def confusion_at_threshold(
    scores: Sequence[float], labels: Sequence[int], threshold: float
) -> ConfusionAtThreshold:
    """Confusion counts + precision/recall for "alert iff score >= threshold".

    precision = TP / (TP + FP) (of fired alerts, how many were real); recall =
    TP / (TP + FN) (of real signals, how many we caught). Precision/recall default to
    0.0 when their denominator is 0 (no alerts fired / no positives exist) -- an honest
    placeholder reported with the raw counts beside it.
    """
    _check_pairs(scores, labels)
    _check_binary_labels(labels)
    tp = fp = tn = fn = 0
    for score, label in zip(scores, labels, strict=True):
        fired = score >= threshold
        if fired and label == 1:
            tp += 1
        elif fired and label == 0:
            fp += 1
        elif not fired and label == 1:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return ConfusionAtThreshold(
        threshold=threshold,
        true_positive=tp,
        false_positive=fp,
        true_negative=tn,
        false_negative=fn,
        precision=precision,
        recall=recall,
    )
