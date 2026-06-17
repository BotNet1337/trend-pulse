"""Unit tests for eval.clustering_audit (TASK-081)."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from eval.clustering_audit import (
    MergeWindowAudit,
    PairLabel,
    audit_duplicate_topics,
    audit_sizes,
    count_duplicate_centroid_pairs,
    count_merge_window_pairs,
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


# ---------------------------------------------------------------------------
# TASK-123: merge-window precision audit (count_merge_window_pairs)
# ---------------------------------------------------------------------------


def _unit_at_angle(deg: float) -> list[float]:
    """A 2-D unit vector at `deg` degrees — cos(angle between two) = cos(Δdeg)."""
    rad = math.radians(deg)
    return [math.cos(rad), math.sin(rad)]


@pytest.mark.unit
def test_count_merge_window_pairs_window_count() -> None:
    """Counts ONLY the pairs whose cosine sim falls in [merge, tight) — the NEW
    merges the looser threshold introduces. Pairs >= tight (already merged by the
    tight tier) and pairs < merge (never merged) are excluded.

    Angles chosen so each pairwise cosine is hand-known:
      v0=0deg, v1=10deg (cos10 ~= 0.985 >= tight) — excluded (already-merged tier),
      v2=50deg (cos(v0,v2)=cos50 ~= 0.643 in [0.65? no] ...) — see explicit pairs.
    """
    # Build vectors at known angles; pairwise sim = cos(|a-b| degrees).
    v = {
        0: _unit_at_angle(0.0),
        1: _unit_at_angle(10.0),  # cos(0,1)=cos10=0.985
        2: _unit_at_angle(44.0),  # cos(0,2)=cos44=0.719 ; cos(1,2)=cos34=0.829
        3: _unit_at_angle(70.0),  # cos(0,3)=cos70=0.342 ; cos(1,3)=cos60=0.5 ; cos(2,3)=cos26=0.898
    }
    centroids = [v[0], v[1], v[2], v[3]]
    merge_thr, tight_thr = 0.65, 0.90
    # Enumerate sims:
    #  (0,1)=0.985 >= tight -> excluded
    #  (0,2)=0.719 in [0.65,0.90) -> COUNT
    #  (0,3)=0.342 < merge -> excluded
    #  (1,2)=0.829 in window -> COUNT
    #  (1,3)=0.500 < merge -> excluded
    #  (2,3)=0.898 in window -> COUNT
    # => 3 window pairs
    assert math.cos(math.radians(44.0)) == pytest.approx(0.7193, abs=1e-3)
    audit = count_merge_window_pairs(
        centroids, merge_threshold=merge_thr, tight_threshold=tight_thr
    )
    assert isinstance(audit, MergeWindowAudit)
    assert audit.window_pair_count == 3
    # No labels passed → over-merge proxy is unavailable (meta missing).
    assert audit.over_merge_pair_count is None
    assert audit.over_merge_fraction is None
    assert audit.labels_available is False


@pytest.mark.unit
def test_count_merge_window_pairs_over_merge_proxy() -> None:
    """With per-cluster labels (topic + channel handles), a window pair is OVER-MERGE
    when it is UNRELATED: different topic string AND no channel-handle overlap. A pair
    sharing a topic OR a channel is treated as related (a true cross-channel story)."""
    # Three vectors all mutually in [0.65, 0.90): 0deg/44deg/ (2,3) handled below.
    centroids = [
        _unit_at_angle(0.0),
        _unit_at_angle(44.0),  # cos(0,1)=0.719 -> window pair
        _unit_at_angle(74.0),  # cos(0,2)=cos74=0.276 (<merge, excluded);
        # cos(1,2)=cos30=0.866 -> window pair
    ]
    labels = [
        PairLabel(topic="ETF approved", channels=frozenset({"@a"})),
        PairLabel(topic="ETF approved", channels=frozenset({"@b"})),  # SAME topic as 0 -> related
        PairLabel(topic="weather report", channels=frozenset({"@c"})),  # unrelated to 1
    ]
    # Window pairs: (0,1) sim 0.719 — related (same topic) ; (1,2) sim 0.866 — UNRELATED
    # (different topic, no channel overlap) -> 1 over-merge of 2 window pairs.
    audit = count_merge_window_pairs(
        centroids,
        merge_threshold=0.65,
        tight_threshold=0.90,
        labels=labels,
    )
    assert audit.window_pair_count == 2
    assert audit.labels_available is True
    assert audit.over_merge_pair_count == 1
    assert audit.over_merge_fraction == pytest.approx(0.5)


@pytest.mark.unit
def test_count_merge_window_pairs_channel_overlap_is_related() -> None:
    """A window pair sharing a channel handle is RELATED even with different topics
    (same outlet covering an evolving story) — not counted as over-merge."""
    centroids = [_unit_at_angle(0.0), _unit_at_angle(44.0)]  # sim 0.719 in window
    labels = [
        PairLabel(topic="topic one", channels=frozenset({"@shared", "@x"})),
        PairLabel(topic="topic two", channels=frozenset({"@shared", "@y"})),  # overlap @shared
    ]
    audit = count_merge_window_pairs(
        centroids, merge_threshold=0.65, tight_threshold=0.90, labels=labels
    )
    assert audit.window_pair_count == 1
    assert audit.over_merge_pair_count == 0
    assert audit.over_merge_fraction == pytest.approx(0.0)


@pytest.mark.unit
def test_count_merge_window_pairs_sample_top_by_cosine() -> None:
    """The sample lists window pairs ordered by DESCENDING cosine (closest first),
    capped at `sample_size`, each carrying its indices + cosine + labels."""
    centroids = [
        _unit_at_angle(0.0),
        _unit_at_angle(44.0),  # (0,1) sim 0.719
        _unit_at_angle(74.0),  # (1,2) sim 0.866
    ]
    labels = [
        PairLabel(topic="t0", channels=frozenset({"@a"})),
        PairLabel(topic="t1", channels=frozenset({"@b"})),
        PairLabel(topic="t2", channels=frozenset({"@c"})),
    ]
    audit = count_merge_window_pairs(
        centroids,
        merge_threshold=0.65,
        tight_threshold=0.90,
        labels=labels,
        sample_size=1,
    )
    assert len(audit.sample) == 1  # capped at sample_size
    top = audit.sample[0]
    # The closest window pair (1,2) at cos 0.866 comes first.
    assert {top.index_a, top.index_b} == {1, 2}
    assert top.cosine == pytest.approx(0.866, abs=1e-3)


@pytest.mark.unit
def test_count_merge_window_pairs_empty_and_singleton() -> None:
    """Degenerate corpora: <2 centroids → zero window pairs, empty sample."""
    for centroids in ([], [[1.0, 0.0]]):
        audit = count_merge_window_pairs(centroids, merge_threshold=0.65, tight_threshold=0.90)
        assert audit.window_pair_count == 0
        assert audit.sample == ()
