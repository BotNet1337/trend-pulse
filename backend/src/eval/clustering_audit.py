"""Clustering-STRUCTURE audit over the prod corpus (TASK-081).

We cannot judge clustering ACCURACY (the source text + post-level vectors are gone),
but we CAN audit structure: how lumpy the clusters are (size histogram, singleton
fraction, mega-buckets) and how much apparent duplication exists (clusters sharing
an identical topic string, and pairs of clusters whose 384-d centroids are near-
identical by cosine similarity). High duplication is a quality smell — it suggests
the clusterer is splitting one story into many clusters.

The pure-counting helpers (size histogram, singletons, duplicate topics) take plain
records and are exhaustively unit-tested. The centroid cosine pass uses numpy on the
9,404 x 384 matrix; the O(n^2) ~= 88M upper-triangle comparison runs in a few seconds
as a one-shot script and is processed in row blocks to bound peak memory.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from eval.corpus import ClusterRecord

# Default cosine-similarity threshold above which two centroids are "duplicates"
# (task spec). Named, not a magic literal (CONVENTIONS).
DUPLICATE_CENTROID_COSINE = 0.9

# Row-block size for the blocked O(n^2) cosine pass — bounds the dense similarity
# slice to (block x n) floats at a time instead of materialising the full n-by-n matrix.
_COSINE_BLOCK_ROWS = 512

# Default cap on how many top merge-window pairs the audit samples for human
# spot-check (TASK-123). Named, not a magic literal (CONVENTIONS).
_DEFAULT_MERGE_SAMPLE_SIZE = 20


@dataclass(frozen=True)
class SizeAudit:
    """Cluster-size structure: total, singletons, top mega-buckets, size histogram.

    `clusters_with_posts` is how many distinct clusters own >= 1 post; `total_clusters`
    is the full cluster count (incl. empty clusters with 0 posts). `singleton_pct` is
    expressed against `total_clusters` (the authoritative denominator that matches the
    prod baseline), NOT against `clusters_with_posts`.
    """

    total_clusters: int
    clusters_with_posts: int
    singleton_count: int
    singleton_pct: float
    top_sizes: tuple[int, ...]
    histogram_edges: tuple[int, ...]
    histogram_counts: tuple[int, ...]


# Size-histogram bin edges (post-count per cluster): 1, 2, 3-5, 6-10, 11-50, 51-500, 500+.
_SIZE_EDGES: tuple[int, ...] = (1, 2, 3, 6, 11, 51, 501)


def audit_sizes(
    cluster_post_counts: dict[int, int],
    *,
    total_clusters: int | None = None,
    top_n: int = 5,
) -> SizeAudit:
    """Audit cluster sizes from a ``cluster_id -> post_count`` map.

    Callers pass `eval.corpus.cluster_sizes(...)`, which omits empty clusters, so the
    size histogram / mega-bucket stats describe clusters that actually carry posts.
    `total_clusters` is the authoritative denominator for `singleton_pct` (the full
    cluster count incl. empties); when omitted it defaults to `clusters_with_posts`.
    """
    sizes = list(cluster_post_counts.values())
    with_posts = len(sizes)
    denom = total_clusters if total_clusters is not None else with_posts
    singletons = sum(1 for s in sizes if s == 1)
    singleton_pct = (singletons / denom * 100.0) if denom else 0.0
    top = tuple(sorted(sizes, reverse=True)[:top_n])
    counts = _size_histogram(sizes)
    return SizeAudit(
        total_clusters=denom,
        clusters_with_posts=with_posts,
        singleton_count=singletons,
        singleton_pct=singleton_pct,
        top_sizes=top,
        histogram_edges=_SIZE_EDGES,
        histogram_counts=counts,
    )


def _size_histogram(sizes: Sequence[int]) -> tuple[int, ...]:
    """Bucket sizes into `_SIZE_EDGES` half-open bins + a final overflow bin."""
    counts = [0] * len(_SIZE_EDGES)
    for size in sizes:
        placed = False
        for i in range(len(_SIZE_EDGES) - 1):
            if _SIZE_EDGES[i] <= size < _SIZE_EDGES[i + 1]:
                counts[i] += 1
                placed = True
                break
        if not placed and size >= _SIZE_EDGES[-1]:
            counts[-1] += 1
    return tuple(counts)


@dataclass(frozen=True)
class TopicDuplicationAudit:
    """Duplicate-topic structure: distinct topics + how many collide on an identical string."""

    total_clusters: int
    distinct_topics: int
    duplicate_topic_groups: int
    clusters_in_duplicate_topics: int


def audit_duplicate_topics(clusters: Sequence[ClusterRecord]) -> TopicDuplicationAudit:
    """Count clusters that share an IDENTICAL topic string (exact-match duplication).

    A "duplicate topic group" is a topic string carried by >= 2 clusters;
    `clusters_in_duplicate_topics` sums the sizes of all such groups.
    """
    topic_counts = Counter(c.topic for c in clusters)
    dup_groups = sum(1 for count in topic_counts.values() if count >= 2)
    clusters_in_dups = sum(count for count in topic_counts.values() if count >= 2)
    return TopicDuplicationAudit(
        total_clusters=len(clusters),
        distinct_topics=len(topic_counts),
        duplicate_topic_groups=dup_groups,
        clusters_in_duplicate_topics=clusters_in_dups,
    )


def count_duplicate_centroid_pairs(
    centroids: Sequence[Sequence[float]],
    *,
    cosine_threshold: float = DUPLICATE_CENTROID_COSINE,
) -> int:
    """Count unordered cluster pairs whose centroid cosine similarity >= `cosine_threshold`.

    Blocked upper-triangle pass: L2-normalise all centroids once, then for each row
    block compute its dot products against all rows and count, per block row, the
    strictly-later columns above the threshold. This counts each pair once (i<j) and
    never materialises the full n-by-n matrix.
    """
    matrix = np.asarray(centroids, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] < 2:
        return 0
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    # Guard zero-vectors (degenerate centroid) → leave as 0 so they never hit 1.0.
    norms[norms == 0] = 1.0
    unit = matrix / norms
    n = unit.shape[0]
    total = 0
    for start in range(0, n, _COSINE_BLOCK_ROWS):
        stop = min(start + _COSINE_BLOCK_ROWS, n)
        sims = unit[start:stop] @ unit.T  # (block, n)
        for local_row in range(stop - start):
            global_row = start + local_row
            # only count columns strictly after this row (upper triangle, i<j)
            later = sims[local_row, global_row + 1 :]
            total += int(np.count_nonzero(later >= cosine_threshold))
    return total


# ---------------------------------------------------------------------------
# Merge-window precision audit (TASK-123 — over-merge guard).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PairLabel:
    """Per-cluster relatedness metadata used as an over-merge proxy.

    `topic` is the cluster's topic string; `channels` is the set of channel handles
    that contribute to the cluster. Two clusters are treated as RELATED (a genuine
    cross-channel story) when they share the same topic string OR overlap on at least
    one channel handle; otherwise an in-window pair is counted as a (proxy) over-merge.
    """

    topic: str
    channels: frozenset[str]


@dataclass(frozen=True)
class MergeWindowPair:
    """One unordered cluster pair whose centroid cosine sits in the merge window."""

    index_a: int
    index_b: int
    cosine: float
    label_a: PairLabel | None
    label_b: PairLabel | None
    is_over_merge: bool | None


@dataclass(frozen=True)
class MergeWindowAudit:
    """Result of `count_merge_window_pairs` — the NEW merges a looser threshold adds.

    `window_pair_count` is the number of unordered cluster pairs whose centroid cosine
    is in ``[merge_threshold, tight_threshold)`` — pairs the loose tier WOULD merge that
    the tight tier would NOT. `over_merge_pair_count` / `over_merge_fraction` are the
    proxy over-merge stats (None when no labels were supplied → "meta missing"). `sample`
    holds the top window pairs by descending cosine for human spot-check.
    """

    window_pair_count: int
    over_merge_pair_count: int | None
    over_merge_fraction: float | None
    labels_available: bool
    sample: tuple[MergeWindowPair, ...]


def _pairs_related(a: PairLabel, b: PairLabel) -> bool:
    """Proxy relatedness: same topic string OR at least one shared channel handle."""
    if a.topic == b.topic:
        return True
    return bool(a.channels & b.channels)


def count_merge_window_pairs(
    centroids: Sequence[Sequence[float]],
    *,
    merge_threshold: float,
    tight_threshold: float,
    labels: Sequence[PairLabel] | None = None,
    sample_size: int = _DEFAULT_MERGE_SAMPLE_SIZE,
) -> MergeWindowAudit:
    """Count candidate merge pairs in the cosine window ``[merge_threshold, tight_threshold)``.

    These are exactly the cross-channel merges a looser cross-batch threshold introduces
    over the tight intra-batch one (TASK-123): pairs the loose tier WOULD collapse into
    one cluster but the tight tier would keep apart. When ``labels`` is provided (parallel
    to ``centroids``), an over-merge PROXY is computed: an in-window pair is flagged as a
    (likely) over-merge when the two clusters are UNRELATED — different topic string AND
    no shared channel handle. Without labels the proxy is unavailable (``None``).

    Pure + typed: no DB/IO. Blocked upper-triangle cosine pass mirrors
    `count_duplicate_centroid_pairs` (L2-normalise once, count i<j above/below bounds),
    but also retains the in-window pairs (capped at `sample_size`, top cosine first) so
    the harness can print a human spot-check sample. Degenerate inputs (<2 centroids,
    zero vectors) behave like the duplicate-pair counter: zero pairs, empty sample.
    """
    if labels is not None and len(labels) != len(centroids):
        raise ValueError(
            f"labels length ({len(labels)}) must match centroids length ({len(centroids)})."
        )

    matrix = np.asarray(centroids, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] < 2:
        return MergeWindowAudit(
            window_pair_count=0,
            over_merge_pair_count=0 if labels is not None else None,
            over_merge_fraction=None,
            labels_available=labels is not None,
            sample=(),
        )

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    # Guard zero-vectors (degenerate centroid) → leave as 0 so they never enter a window.
    norms[norms == 0] = 1.0
    unit = matrix / norms
    n = unit.shape[0]

    window_pairs: list[MergeWindowPair] = []
    over_merge = 0
    for start in range(0, n, _COSINE_BLOCK_ROWS):
        stop = min(start + _COSINE_BLOCK_ROWS, n)
        sims = unit[start:stop] @ unit.T  # (block, n)
        for local_row in range(stop - start):
            i = start + local_row
            row = sims[local_row]
            for j in range(i + 1, n):
                cosine = float(row[j])
                if merge_threshold <= cosine < tight_threshold:
                    label_a = labels[i] if labels is not None else None
                    label_b = labels[j] if labels is not None else None
                    related: bool | None = None
                    if label_a is not None and label_b is not None:
                        related = _pairs_related(label_a, label_b)
                    is_over_merge = (related is False) if related is not None else None
                    if is_over_merge:
                        over_merge += 1
                    window_pairs.append(
                        MergeWindowPair(
                            index_a=i,
                            index_b=j,
                            cosine=cosine,
                            label_a=label_a,
                            label_b=label_b,
                            is_over_merge=is_over_merge,
                        )
                    )

    window_pair_count = len(window_pairs)
    over_merge_pair_count = over_merge if labels is not None else None
    over_merge_fraction = (
        (over_merge / window_pair_count) if (labels is not None and window_pair_count) else None
    )
    sample = tuple(
        sorted(window_pairs, key=lambda p: p.cosine, reverse=True)[: max(0, sample_size)]
    )
    return MergeWindowAudit(
        window_pair_count=window_pair_count,
        over_merge_pair_count=over_merge_pair_count,
        over_merge_fraction=over_merge_fraction,
        labels_available=labels is not None,
        sample=sample,
    )
