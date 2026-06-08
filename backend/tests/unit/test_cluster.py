"""AC4 — cluster groups semantically-close vectors; far post stands alone."""

from datetime import UTC, datetime

import pytest

from collector.base import PostMetrics, SourceKind, SourceRef
from pipeline.steps import cluster
from pipeline.steps.cluster import ClusterCandidate
from pipeline.steps.normalize import NormalizedPost


def _post(external_id: str, handle: str = "@chan") -> NormalizedPost:
    return NormalizedPost(
        source=SourceRef(kind=SourceKind.TELEGRAM, handle=handle),
        external_id=external_id,
        text=f"post {external_id}",
        metrics=PostMetrics(views=1, forwards=0, reactions=0),
        posted_at=datetime(2026, 6, 8, tzinfo=UTC),
    )


def test_cluster_groups_close_and_separates_far() -> None:
    posts = [_post("1"), _post("2"), _post("3")]
    # Two near-identical unit vectors (cosine ~1.0) + one orthogonal (cosine 0).
    vectors = [
        [1.0, 0.0, 0.0],
        [0.99, 0.01, 0.0],
        [0.0, 1.0, 0.0],
    ]
    candidates = cluster.run(posts, vectors)
    # One cluster for the close pair, one for the far post.
    assert len(candidates) == 2
    sizes = sorted(len(c.posts) for c in candidates)
    assert sizes == [1, 2]


def test_cluster_threshold_drives_grouping() -> None:
    # Two pairs each internally close, the pairs far from each other.
    posts = [_post(str(i)) for i in range(4)]
    vectors = [
        [1.0, 0.0],
        [0.98, 0.02],
        [0.0, 1.0],
        [0.02, 0.98],
    ]
    candidates = cluster.run(posts, vectors)
    assert len(candidates) == 2
    assert all(len(c.posts) == 2 for c in candidates)


def test_cluster_single_post_is_valid_cluster() -> None:
    candidates = cluster.run([_post("1")], [[1.0, 0.0, 0.0]])
    assert len(candidates) == 1
    assert len(candidates[0].posts) == 1
    assert isinstance(candidates[0], ClusterCandidate)


def test_cluster_empty_input() -> None:
    assert cluster.run([], []) == []


def test_cluster_zero_vector_no_division_error() -> None:
    # Degenerate zero vector must not raise (guarded cosine).
    candidates = cluster.run([_post("1"), _post("2")], [[0.0, 0.0], [0.0, 0.0]])
    # Zero vectors have 0 cosine to everything → each stands alone.
    assert len(candidates) == 2


def test_cluster_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        cluster.run([_post("1")], [[1.0], [2.0]])


def test_cluster_aggregates_distinct_handles() -> None:
    posts = [_post("1", "@a"), _post("2", "@b")]
    vectors = [[1.0, 0.0], [0.99, 0.0]]
    candidates = cluster.run(posts, vectors)
    assert len(candidates) == 1
    assert set(candidates[0].handles) == {"@a", "@b"}


def test_cluster_candidate_is_frozen() -> None:
    candidates = cluster.run([_post("1")], [[1.0, 0.0]])
    with pytest.raises(AttributeError):
        candidates[0].topic = "changed"  # type: ignore[misc]
