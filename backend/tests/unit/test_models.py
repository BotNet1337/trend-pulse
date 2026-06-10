"""AC1 RED→GREEN anchor: ORM contract for the TrendPulse data model.

Introspects mappers/columns ONLY — never opens a DB connection, so it runs in
`make ci-fast` (marker: not integration). Verifies:
- all 7 models + `Base` import from `storage`,
- `Cluster.embedding` is a pgvector `Vector` of dimension `EMBEDDING_DIM == 384`,
- user-owned tables carry a `user_id` FK → `users.id` with `ondelete="CASCADE"`,
- `Channel` has NO `user_id`,
- every datetime column is `DateTime(timezone=True)`.
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase

from storage import (
    EMBEDDING_DIM,
    Alert,
    Base,
    Channel,
    Cluster,
    Post,
    Score,
    Watchlist,
)

_EXPECTED_DIM = 384
_USER_OWNED = (Watchlist, Post, Cluster, Score, Alert)


def test_embedding_dim_is_384() -> None:
    assert EMBEDDING_DIM == _EXPECTED_DIM


def test_base_is_declarative() -> None:
    assert issubclass(Base, DeclarativeBase)


def test_all_models_share_base_metadata() -> None:
    tables = set(Base.metadata.tables)
    assert tables == {
        "users",
        "oauth_accounts",
        "channels",
        "watchlists",
        "posts",
        "clusters",
        "scores",
        "alerts",
        "subscriptions",
        "billing_payments",
        "api_keys",  # TASK-028: Team-plan API keys
        "alert_feedback",  # TASK-042: 👍/👎 verdict per alert
        "showcase_posts",  # TASK-044: showcase autopost dedup table
    }


def test_cluster_embedding_is_vector_384() -> None:
    col = Cluster.__table__.c.embedding
    assert isinstance(col.type, Vector)
    assert col.type.dim == _EXPECTED_DIM


def test_post_embedding_is_nullable_vector_384() -> None:
    col = Post.__table__.c.embedding
    assert isinstance(col.type, Vector)
    assert col.type.dim == _EXPECTED_DIM
    assert col.nullable is True


def test_user_owned_tables_have_cascading_user_fk() -> None:
    for model in _USER_OWNED:
        user_id = model.__table__.c.user_id
        assert user_id is not None, f"{model.__name__} missing user_id"
        fks = list(user_id.foreign_keys)
        assert len(fks) == 1, f"{model.__name__}.user_id must have exactly one FK"
        fk = fks[0]
        assert fk.column.table.name == "users"
        assert fk.column.name == "id"
        assert fk.ondelete == "CASCADE", f"{model.__name__}.user_id FK not CASCADE"


def test_channel_has_no_user_id() -> None:
    assert "user_id" not in Channel.__table__.c


def test_channel_unique_source_kind_handle() -> None:
    cols = {
        tuple(sorted(c.name for c in uc.columns))
        for uc in Channel.__table__.constraints
        if hasattr(uc, "columns")
    }
    assert ("handle", "source_kind") in cols


def test_all_datetime_columns_are_timezone_aware() -> None:
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, DateTime):
                assert col.type.timezone is True, f"{table.name}.{col.name} not tz-aware"
