"""AC3 (integration): `delete_user` removes ALL user-owned rows via cascade.

Against a real pgvector Postgres (marker `integration`): seed a user with rows in
every user-owned table (watchlists, posts, clusters, scores, alerts), call
`delete_user`, then assert 0 rows remain for that `user_id` across all of them
(no orphans). Proves the schema's `ON DELETE CASCADE` (task-002) is wired on every
FK — `delete_user` issues a SINGLE delete and never enumerates child tables.
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from compliance.account import delete_user
from storage.models.alerts import Alert
from storage.models.base import utcnow
from storage.models.channels import Channel, SourceKind
from storage.models.clusters import EMBEDDING_DIM, Cluster
from storage.models.posts import Post
from storage.models.scores import Score
from storage.models.users import User
from storage.models.watchlists import Watchlist

pytestmark = pytest.mark.integration


def _seed_user_with_dependents(session: Session) -> int:
    """Create one user owning a row in every user-owned table; return the user id."""
    user = User(email="erase-me@example.com", hashed_password="x" * 16)
    session.add(user)
    session.flush()

    channel = Channel(source_kind=SourceKind.TELEGRAM, handle="@cascade_test")
    session.add(channel)
    session.flush()

    now = utcnow()
    cluster = Cluster(
        user_id=user.id, topic="ai", embedding=[0.0] * EMBEDDING_DIM, first_seen=now, updated_at=now
    )
    session.add(cluster)
    session.flush()

    session.add_all(
        [
            Watchlist(user_id=user.id, channel_id=channel.id, topic="ai"),
            Post(
                user_id=user.id,
                channel_id=channel.id,
                external_id="p1",
                posted_at=now - timedelta(hours=1),
                fetched_at=now - timedelta(hours=1),
                text="raw",
            ),
            Score(
                user_id=user.id,
                cluster_id=cluster.id,
                velocity=1.0,
                engagement=1.0,
                cross_channel=1.0,
                viral_score=80.0,
            ),
            Alert(user_id=user.id, cluster_id=cluster.id, score=80.0, channels_count=2),
        ]
    )
    session.commit()
    return user.id


def test_delete_user_leaves_no_orphans(db_session: Session) -> None:
    user_id = _seed_user_with_dependents(db_session)

    deleted = delete_user(db_session, user_id)
    db_session.commit()
    assert deleted == 1

    user_owned = [User, Watchlist, Post, Cluster, Score, Alert]
    for model in user_owned:
        id_col = User.id if model is User else model.user_id
        count = db_session.execute(
            select(func.count()).select_from(model).where(id_col == user_id)
        ).scalar_one()
        assert count == 0, f"orphan rows left in {model.__tablename__}"
