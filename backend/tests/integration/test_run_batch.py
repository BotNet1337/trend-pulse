"""Integration (G2) — real Redis buffer + Postgres + real embedding model.

Seeds a user's source buffer, runs `process_user_batch(user_id)`, and asserts
clusters are persisted scoped by that user_id. The real sentence-transformers
model is used; the whole module is SKIPPED when the `ml` stack is unavailable so
`make ci-fast` / CI-without-ml never fail to import.
"""

from datetime import UTC, datetime

import fakeredis
import pytest
from sqlalchemy.orm import Session

from collector.base import PostMetrics, RawPost, SourceKind, SourceRef
from collector.buffer import write_post
from storage.models import EMBEDDING_DIM, Channel, Cluster, Post, User, Watchlist
from storage.models.channels import SourceKind as ChannelSourceKind

pytestmark = pytest.mark.integration


def _batch_processor() -> object:
    """Skip-guard the ml stack and import the processor INSIDE the test.

    Per-test (not module-level) so pytest COLLECTION never imports
    sentence_transformers/torch — otherwise collecting this deselected module
    would pollute sys.modules and break the embed lazy-import unit test when the
    `ml` group is installed locally (arch §7: ml is opt-in).
    """
    pytest.importorskip("sentence_transformers")
    from pipeline import batch_processor

    return batch_processor


def _raw(external_id: str, text: str, handle: str) -> RawPost:
    return RawPost(
        source=SourceRef(kind=SourceKind.TELEGRAM, handle=handle),
        external_id=external_id,
        author="author",
        text=text,
        media_hashes=(),
        metrics=PostMetrics(views=100, forwards=5, reactions=10),
        posted_at=datetime(2026, 6, 8, tzinfo=UTC),
    )


def test_run_batch_persists_clusters_scoped_by_user(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = "@viralnews"
    user = User(email="batch@example.com", hashed_password="x" * 16)
    db_session.add(user)
    db_session.flush()
    channel = Channel(source_kind=ChannelSourceKind.TELEGRAM, handle=handle)
    db_session.add(channel)
    db_session.flush()
    db_session.add(Watchlist(user_id=user.id, channel_id=channel.id, topic="news", lang="en"))
    db_session.commit()
    user_id = user.id

    # Seed a real-shaped buffer in fakeredis: two near-identical posts (collapse on
    # dedup) + one distinct post → expect at least one cluster.
    redis = fakeredis.FakeRedis()
    write_post(redis, _raw("1", "The central bank raised rates again today", handle))
    write_post(redis, _raw("2", "The central bank raised rates again today!", handle))
    write_post(redis, _raw("3", "A new indie game about gardening won awards", handle))

    batch_processor = _batch_processor()
    monkeypatch.setattr(batch_processor, "get_redis_client", lambda: redis)

    count = batch_processor.process_user_batch(user_id)

    assert count >= 1
    db_session.expire_all()
    rows = db_session.query(Cluster).filter(Cluster.user_id == user_id).all()
    assert len(rows) == count
    assert all(r.user_id == user_id for r in rows)
    assert all(len(r.embedding) > 0 for r in rows)

    # TASK-082: per-post embeddings persisted (real model) — every Post row now carries
    # a non-null 384-d vector (the one used for its cluster), so vectors survive the
    # 48h text purge and the corpus becomes backtestable.
    posts_persisted = db_session.query(Post).filter(Post.user_id == user_id).all()
    assert posts_persisted, "expected member posts to be persisted"
    for post in posts_persisted:
        assert post.embedding is not None
        assert len(post.embedding) == EMBEDDING_DIM


def test_second_batch_same_topic_merges_into_one_cluster(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC2 (real pgvector): running two batches whose posts describe the SAME topic
    yields ONE cluster, not two — the second batch's candidate merges into the
    first batch's cluster instead of spawning a duplicate.
    """
    handle = "@viralnews"
    user = User(email="merge@example.com", hashed_password="x" * 16)
    db_session.add(user)
    db_session.flush()
    channel = Channel(source_kind=ChannelSourceKind.TELEGRAM, handle=handle)
    db_session.add(channel)
    db_session.flush()
    db_session.add(Watchlist(user_id=user.id, channel_id=channel.id, topic="news", lang="en"))
    db_session.commit()
    user_id = user.id

    batch_processor = _batch_processor()

    # Batch 1: one topic.
    redis1 = fakeredis.FakeRedis()
    write_post(redis1, _raw("1", "The central bank raised interest rates today", handle))
    monkeypatch.setattr(batch_processor, "get_redis_client", lambda: redis1)
    count1 = batch_processor.process_user_batch(user_id)
    assert count1 == 1

    # Batch 2: same topic, fresh external_id → must MERGE into the existing cluster.
    redis2 = fakeredis.FakeRedis()
    write_post(redis2, _raw("2", "The central bank raised interest rates again today", handle))
    monkeypatch.setattr(batch_processor, "get_redis_client", lambda: redis2)
    batch_processor.process_user_batch(user_id)

    db_session.expire_all()
    rows = db_session.query(Cluster).filter(Cluster.user_id == user_id).all()
    # The defect produced 2 rows; the fix yields exactly 1.
    assert len(rows) == 1


def test_ancient_cluster_not_merged_creates_new(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC4 (real pgvector): a same-topic but STALE cluster (updated_at older than
    the merge window) is NOT merged into — a fresh cluster is created instead.
    """
    from datetime import timedelta

    from config import get_settings
    from storage.models.base import utcnow

    handle = "@viralnews"
    user = User(email="ancient@example.com", hashed_password="x" * 16)
    db_session.add(user)
    db_session.flush()
    channel = Channel(source_kind=ChannelSourceKind.TELEGRAM, handle=handle)
    db_session.add(channel)
    db_session.flush()
    db_session.add(Watchlist(user_id=user.id, channel_id=channel.id, topic="news", lang="en"))
    db_session.commit()
    user_id = user.id

    batch_processor = _batch_processor()

    # Batch 1 → one cluster.
    redis1 = fakeredis.FakeRedis()
    write_post(redis1, _raw("1", "The central bank raised interest rates today", handle))
    monkeypatch.setattr(batch_processor, "get_redis_client", lambda: redis1)
    assert batch_processor.process_user_batch(user_id) == 1

    # Age that cluster beyond the merge freshness window.
    stale_at = utcnow() - timedelta(seconds=get_settings().cluster_merge_window_seconds + 3600)
    db_session.query(Cluster).filter(Cluster.user_id == user_id).update(
        {Cluster.updated_at: stale_at}
    )
    db_session.commit()

    # Batch 2: same topic, but the only existing cluster is stale → new cluster.
    redis2 = fakeredis.FakeRedis()
    write_post(redis2, _raw("2", "The central bank raised interest rates again today", handle))
    monkeypatch.setattr(batch_processor, "get_redis_client", lambda: redis2)
    batch_processor.process_user_batch(user_id)

    db_session.expire_all()
    rows = db_session.query(Cluster).filter(Cluster.user_id == user_id).all()
    assert len(rows) == 2


def test_run_batch_empty_buffer_is_no_op(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = User(email="empty@example.com", hashed_password="x" * 16)
    db_session.add(user)
    db_session.commit()
    user_id = user.id

    redis = fakeredis.FakeRedis()
    batch_processor = _batch_processor()
    monkeypatch.setattr(batch_processor, "get_redis_client", lambda: redis)

    count = batch_processor.process_user_batch(user_id)

    assert count == 0
    db_session.expire_all()
    rows = db_session.query(Cluster).filter(Cluster.user_id == user_id).all()
    assert rows == []
