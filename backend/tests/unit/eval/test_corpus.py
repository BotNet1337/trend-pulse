"""Unit tests for eval.corpus parsing/loading helpers (TASK-081)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from eval.corpus import (
    CorpusParseError,
    cluster_sizes,
    load_clusters,
    load_posts,
    parse_centroid,
)

_POSTS_CSV = (
    "id,posted_at,channel_id,user_id,cluster_id,views,forwards,reactions\n"
    "1,2026-06-12 14:15:57+00,4,10,1,360,1,7\n"
    "2,2026-06-12 15:00:00+00,5,10,1,100,0,0\n"
    "3,2026-06-12 16:00:00+00,4,10,,50,0,0\n"  # orphan post (cluster_id NULL)
)

_CLUSTERS_CSV = (
    "id,user_id,first_seen,updated_at,topic,embedding\n"
    "1,10,2026-06-12 17:48:01+00,2026-06-12 17:48:01+00,"
    '"Topic, with comma","[0.1,0.2,0.3]"\n'
    "2,10,2026-06-12 18:00:00+00,2026-06-12 18:00:00+00,Plain topic,"
    '"[1.0,0.0,0.0]"\n'
)


@pytest.mark.unit
def test_load_posts_parses_metrics_and_null_cluster(tmp_path: Path) -> None:
    path = tmp_path / "posts.csv"
    path.write_text(_POSTS_CSV, encoding="utf-8")
    posts = load_posts(path)
    assert len(posts) == 3
    assert posts[0].views == 360
    assert posts[0].cluster_id == 1
    assert posts[0].posted_at == datetime(2026, 6, 12, 14, 15, 57, tzinfo=UTC)
    assert posts[2].cluster_id is None  # NULL cluster_id parsed as None


@pytest.mark.unit
def test_load_clusters_parses_topic_and_centroid(tmp_path: Path) -> None:
    path = tmp_path / "clusters.csv"
    path.write_text(_CLUSTERS_CSV, encoding="utf-8")
    clusters = load_clusters(path)
    assert len(clusters) == 2
    assert clusters[0].topic == "Topic, with comma"  # CSV-quoted comma preserved
    assert clusters[0].centroid == (0.1, 0.2, 0.3)
    assert clusters[1].centroid == (1.0, 0.0, 0.0)


@pytest.mark.unit
def test_parse_centroid_round_trips_pgvector_literal() -> None:
    assert parse_centroid("[0.5,-0.25,1.0]") == (0.5, -0.25, 1.0)


@pytest.mark.unit
def test_parse_centroid_rejects_non_literal() -> None:
    with pytest.raises(CorpusParseError):
        parse_centroid("0.1,0.2")
    with pytest.raises(CorpusParseError):
        parse_centroid("[]")


@pytest.mark.unit
def test_cluster_sizes_skips_orphans(tmp_path: Path) -> None:
    path = tmp_path / "posts.csv"
    path.write_text(_POSTS_CSV, encoding="utf-8")
    sizes = cluster_sizes(load_posts(path))
    assert sizes == {1: 2}  # post 3 is an orphan → not counted


@pytest.mark.unit
def test_load_posts_raises_on_bad_int(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(
        "id,posted_at,channel_id,user_id,cluster_id,views,forwards,reactions\n"
        "1,2026-06-12 14:15:57+00,4,10,1,NOTANINT,1,7\n",
        encoding="utf-8",
    )
    with pytest.raises(CorpusParseError):
        load_posts(path)
