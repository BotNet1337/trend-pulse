"""Unit tests for eval.clustering_audit (TASK-081)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from eval.clustering_audit import (
    audit_duplicate_topics,
    audit_sizes,
    count_duplicate_centroid_pairs,
)
from eval.corpus import ClusterRecord

_T = datetime(2026, 6, 12, tzinfo=UTC)


def _cluster(cid: int, topic: str, centroid: tuple[float, ...]) -> ClusterRecord:
    return ClusterRecord(
        id=cid, user_id=10, first_seen=_T, updated_at=_T, topic=topic, centroid=centroid
    )


@pytest.mark.unit
def test_audit_sizes_singletons_and_mega() -> None:
    counts = {1: 1, 2: 1, 3: 1, 4: 4102, 5: 1713, 6: 3}
    audit = audit_sizes(counts, top_n=3)
    assert audit.total_clusters == 6  # defaults to clusters_with_posts
    assert audit.clusters_with_posts == 6
    assert audit.singleton_count == 3
    assert audit.singleton_pct == pytest.approx(50.0)
    assert audit.top_sizes == (4102, 1713, 3)


@pytest.mark.unit
def test_audit_sizes_singleton_pct_against_total_clusters() -> None:
    # 3 singletons among 6 clusters-with-posts, but 10 total clusters (4 empty)
    counts = {1: 1, 2: 1, 3: 1, 4: 4102, 5: 1713, 6: 3}
    audit = audit_sizes(counts, total_clusters=10, top_n=3)
    assert audit.total_clusters == 10
    assert audit.clusters_with_posts == 6
    assert audit.singleton_pct == pytest.approx(30.0)  # 3/10


@pytest.mark.unit
def test_audit_sizes_histogram_bins() -> None:
    # sizes: three 1s, one 2, one 4 (3-5 bin), one 600 (overflow 501+)
    counts = {1: 1, 2: 1, 3: 1, 4: 2, 5: 4, 6: 600}
    audit = audit_sizes(counts)
    # edges (1,2,3,6,11,51,501): bins = [1],[2],[3-5],[6-10],[11-50],[51-500],[501+]
    assert audit.histogram_edges == (1, 2, 3, 6, 11, 51, 501)
    assert audit.histogram_counts == (3, 1, 1, 0, 0, 0, 1)


@pytest.mark.unit
def test_audit_duplicate_topics() -> None:
    clusters = [
        _cluster(1, "Bitcoin ETF", (1.0,)),
        _cluster(2, "Bitcoin ETF", (1.0,)),  # dup of 1
        _cluster(3, "Bitcoin ETF", (1.0,)),  # dup of 1
        _cluster(4, "Ethereum", (1.0,)),
        _cluster(5, "Solana", (1.0,)),
        _cluster(6, "Solana", (1.0,)),  # dup of 5
    ]
    audit = audit_duplicate_topics(clusters)
    assert audit.total_clusters == 6
    assert audit.distinct_topics == 3  # Bitcoin ETF, Ethereum, Solana
    assert audit.duplicate_topic_groups == 2  # Bitcoin ETF (3), Solana (2)
    assert audit.clusters_in_duplicate_topics == 5  # 3 + 2


@pytest.mark.unit
def test_count_duplicate_centroid_pairs_cosine() -> None:
    centroids = [
        [1.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],  # identical → cos 1.0 with #0
        [0.99, 0.01, 0.0],  # near-identical to #0/#1 → >= 0.9
        [0.0, 1.0, 0.0],  # orthogonal → cos 0
    ]
    # pairs >= 0.9: (0,1),(0,2),(1,2) = 3
    assert count_duplicate_centroid_pairs(centroids, cosine_threshold=0.9) == 3


@pytest.mark.unit
def test_count_duplicate_centroid_pairs_handles_block_boundary() -> None:
    # 600 identical vectors crosses the 512-row block boundary; all pairs are dups.
    n = 600
    centroids = [[1.0, 0.0]] * n
    expected = n * (n - 1) // 2
    assert count_duplicate_centroid_pairs(centroids, cosine_threshold=0.9) == expected


@pytest.mark.unit
def test_count_duplicate_centroid_pairs_empty() -> None:
    assert count_duplicate_centroid_pairs([], cosine_threshold=0.9) == 0
    assert count_duplicate_centroid_pairs([[1.0, 0.0]], cosine_threshold=0.9) == 0
