"""AC4-AC7: round-trip, cascade delete, tenant scoping, tz-aware datetimes."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from storage import (
    EMBEDDING_DIM,
    Alert,
    Channel,
    Cluster,
    Post,
    Score,
    SourceKind,
    User,
    Watchlist,
)
from storage.repositories import (
    ChannelRepository,
    ClusterRepository,
)

pytestmark = pytest.mark.integration


def _make_user(session: Session, email: str) -> User:
    # hashed_password is NOT NULL since TASK-003 aligned `users` with fastapi-users;
    # a placeholder hash is enough for storage round-trip/cascade/scoping tests.
    user = User(email=email, hashed_password="x" * 16)
    session.add(user)
    session.flush()
    return user


def test_channel_get_or_create_is_global_and_deduped(db_session: Session) -> None:
    repo = ChannelRepository()
    a = repo.get_or_create(db_session, source_kind=SourceKind.TELEGRAM, handle="@news")
    b = repo.get_or_create(db_session, source_kind=SourceKind.TELEGRAM, handle="@news")
    db_session.commit()
    assert a.id == b.id  # deduped on (source_kind, handle)


def test_round_trip_embedding_preserves_dimension(db_session: Session) -> None:  # AC4
    user = _make_user(db_session, "rt@example.com")
    channel = ChannelRepository().get_or_create(
        db_session, source_kind=SourceKind.TELEGRAM, handle="@rt"
    )
    db_session.flush()

    vec = [0.1 * i for i in range(EMBEDDING_DIM)]
    post = Post(
        user_id=user.id,
        channel_id=channel.id,
        external_id="ext-1",
        views=10,
        forwards=2,
        reactions=3,
        embedding=vec,
        posted_at=datetime.now(UTC),
    )
    cluster = Cluster(user_id=user.id, topic="ai", embedding=vec)
    db_session.add_all([post, cluster])
    db_session.commit()
    db_session.expire_all()

    read_post = db_session.get(Post, post.id)
    read_cluster = db_session.get(Cluster, cluster.id)
    assert read_post is not None
    assert read_cluster is not None
    assert read_post.embedding is not None
    assert len(read_post.embedding) == EMBEDDING_DIM
    assert len(read_cluster.embedding) == EMBEDDING_DIM
    assert read_post.embedding[1] == pytest.approx(0.1)


def test_cascade_delete_removes_tenant_rows_keeps_channels(db_session: Session) -> None:  # AC5
    user = _make_user(db_session, "cascade@example.com")
    channel = ChannelRepository().get_or_create(
        db_session, source_kind=SourceKind.TELEGRAM, handle="@cascade"
    )
    db_session.flush()
    vec = [0.0] * EMBEDDING_DIM
    cluster = Cluster(user_id=user.id, topic="t", embedding=vec)
    db_session.add(cluster)
    db_session.flush()
    db_session.add_all(
        [
            Watchlist(
                user_id=user.id,
                channel_id=channel.id,
                topic="t",
                threshold=0.5,
                min_channels=1,
                lang="en",
            ),
            Post(
                user_id=user.id,
                channel_id=channel.id,
                external_id="e1",
                views=1,
                forwards=0,
                reactions=0,
                posted_at=datetime.now(UTC),
            ),
            Score(
                user_id=user.id,
                cluster_id=cluster.id,
                velocity=1.0,
                engagement=1.0,
                cross_channel=1.0,
                viral_score=1.0,
            ),
            Alert(
                user_id=user.id,
                cluster_id=cluster.id,
                score=1.0,
                channels_count=1,
            ),
        ]
    )
    db_session.commit()

    db_session.delete(db_session.get(User, user.id))
    db_session.commit()

    for model in (Watchlist, Post, Cluster, Score, Alert):
        count = db_session.scalar(
            select(func.count()).select_from(model).where(model.user_id == user.id)
        )
        assert count == 0, f"{model.__name__} rows not cascaded"
    assert db_session.get(Channel, channel.id) is not None  # global, kept


def test_cluster_repo_is_user_scoped(db_session: Session) -> None:  # AC6
    user_a = _make_user(db_session, "a@example.com")
    user_b = _make_user(db_session, "b@example.com")
    vec = [0.0] * EMBEDDING_DIM
    db_session.add_all(
        [
            Cluster(user_id=user_a.id, topic="a", embedding=vec),
            Cluster(user_id=user_b.id, topic="b", embedding=vec),
        ]
    )
    db_session.commit()

    repo = ClusterRepository()
    rows_a = repo.list(db_session, user_id=user_a.id)
    assert len(rows_a) == 1
    assert all(c.user_id == user_a.id for c in rows_a)


def test_datetime_round_trip_is_tz_aware_utc(db_session: Session) -> None:  # AC7
    user = _make_user(db_session, "tz@example.com")
    db_session.commit()
    db_session.expire_all()

    read = db_session.get(User, user.id)
    assert read is not None
    assert read.created_at.tzinfo is not None
    assert read.created_at.utcoffset() == datetime.now(UTC).utcoffset()
