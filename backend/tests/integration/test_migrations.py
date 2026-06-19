"""AC2/AC3: `alembic upgrade head` on a live pgvector DB.

Asserts the `vector` extension is present (AC3), all seven tables exist (AC2),
and `alembic current` reports the baseline revision.
"""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from config import get_settings

pytestmark = pytest.mark.integration

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_BASELINE_REVISION = "0001"
_EXPECTED_TABLES = {
    "users",
    "channels",
    "watchlists",
    "posts",
    "clusters",
    "scores",
    "alerts",
    "subscriptions",
    "billing_payments",
    "cluster_feature_snapshots",  # TASK-109 (0023): forward feature-snapshot capture
    "pool_sessions",  # TASK-119 (0024): dynamic encrypted pool session store
    "factory_accounts",  # TASK-132 (0028): account-factory provisioning lifecycle
}


def _alembic_config() -> Config:
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    return cfg


def test_upgrade_head_creates_schema_with_vector_extension() -> None:
    from alembic import command

    engine = create_engine(get_settings().database_url)
    try:
        # Start clean so the migration (not create_all) builds the schema.
        # Drop EVERY table in public dynamically — a hardcoded list silently
        # rots when a migration adds a table (api_keys, 0010) and leaves the
        # schema half-built, cascading failures into every later test.
        with engine.begin() as conn:
            tables = (
                conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
                .scalars()
                .all()
            )
            for table in tables:
                conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))

        command.upgrade(_alembic_config(), "head")

        with engine.connect() as conn:
            ext = conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            ).fetchone()
            assert ext is not None  # AC3

        tables = set(inspect(engine).get_table_names())
        assert tables >= _EXPECTED_TABLES  # AC2

        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
        head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
        # After `upgrade head` the DB is at the latest revision (now 0002_auth,
        # not just the 0001 baseline). Assert it tracked head rather than a literal.
        assert head is not None
        assert current == head
    finally:
        engine.dispose()


def test_billing_payment_url_migration_up_down() -> None:
    """0021 (TASK-048): upgrade adds `billing_payments.payment_url` (nullable),
    downgrade drops it cleanly, and re-upgrade restores it."""
    from alembic import command

    def _billing_columns(engine_: object) -> set[str]:
        return {col["name"] for col in inspect(engine_).get_columns("billing_payments")}

    engine = create_engine(get_settings().database_url)
    try:
        # Self-contained: rebuild the schema via alembic regardless of test order.
        with engine.begin() as conn:
            tables = (
                conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
                .scalars()
                .all()
            )
            for table in tables:
                conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))

        command.upgrade(_alembic_config(), "head")
        assert "payment_url" in _billing_columns(engine)

        command.downgrade(_alembic_config(), "0020")
        assert "payment_url" not in _billing_columns(engine)

        command.upgrade(_alembic_config(), "head")
        assert "payment_url" in _billing_columns(engine)
    finally:
        engine.dispose()


def test_cluster_feature_snapshots_migration_up_down() -> None:
    """0023 (TASK-109): upgrade creates `cluster_feature_snapshots`, downgrade drops it
    cleanly, and re-upgrade restores it (with the idempotency unique constraint)."""
    from alembic import command

    def _has_table(engine_: object) -> bool:
        return "cluster_feature_snapshots" in inspect(engine_).get_table_names()

    engine = create_engine(get_settings().database_url)
    try:
        with engine.begin() as conn:
            tables = (
                conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
                .scalars()
                .all()
            )
            for table in tables:
                conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))

        command.upgrade(_alembic_config(), "head")
        assert _has_table(engine)
        uniques = {
            u["name"] for u in inspect(engine).get_unique_constraints("cluster_feature_snapshots")
        }
        assert "uq_cluster_feature_snapshots_user_cluster_window" in uniques

        command.downgrade(_alembic_config(), "0022")
        assert not _has_table(engine)

        command.upgrade(_alembic_config(), "head")
        assert _has_table(engine)
    finally:
        engine.dispose()


def test_pool_sessions_migration_up_down() -> None:
    """0024 (TASK-119): upgrade creates `pool_sessions` with the tg_user_id unique
    constraint, downgrade drops it cleanly, and re-upgrade restores it."""
    from alembic import command

    def _has_table(engine_: object) -> bool:
        return "pool_sessions" in inspect(engine_).get_table_names()

    engine = create_engine(get_settings().database_url)
    try:
        with engine.begin() as conn:
            tables = (
                conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
                .scalars()
                .all()
            )
            for table in tables:
                conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))

        command.upgrade(_alembic_config(), "head")
        assert _has_table(engine)
        uniques = {u["name"] for u in inspect(engine).get_unique_constraints("pool_sessions")}
        assert "uq_pool_sessions_tg_user_id" in uniques

        command.downgrade(_alembic_config(), "0023")
        assert not _has_table(engine)

        command.upgrade(_alembic_config(), "head")
        assert _has_table(engine)
    finally:
        engine.dispose()


def test_factory_accounts_migration_up_down() -> None:
    """0028 (TASK-132): upgrade creates `factory_accounts` with the `state` and
    `probation_until` indexes, downgrade drops it cleanly, and re-upgrade restores it."""
    from alembic import command

    def _has_table(engine_: object) -> bool:
        return "factory_accounts" in inspect(engine_).get_table_names()

    engine = create_engine(get_settings().database_url)
    try:
        with engine.begin() as conn:
            tables = (
                conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
                .scalars()
                .all()
            )
            for table in tables:
                conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))

        command.upgrade(_alembic_config(), "head")
        assert _has_table(engine)
        indexes = {ix["name"] for ix in inspect(engine).get_indexes("factory_accounts")}
        assert "ix_factory_accounts_state" in indexes
        assert "ix_factory_accounts_probation_until" in indexes

        command.downgrade(_alembic_config(), "0027")
        assert not _has_table(engine)

        command.upgrade(_alembic_config(), "head")
        assert _has_table(engine)
    finally:
        engine.dispose()


def test_scores_effective_sources_migration_up_down() -> None:
    """0025 (TASK-126): upgrade adds `scores.effective_sources` (nullable double
    precision), downgrade drops it cleanly, and re-upgrade restores it."""
    from alembic import command

    def _effective_sources_column(engine_: object) -> dict[str, object] | None:
        for col in inspect(engine_).get_columns("scores"):
            if col["name"] == "effective_sources":
                return col
        return None

    engine = create_engine(get_settings().database_url)
    try:
        with engine.begin() as conn:
            tables = (
                conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
                .scalars()
                .all()
            )
            for table in tables:
                conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))

        command.upgrade(_alembic_config(), "head")
        column = _effective_sources_column(engine)
        assert column is not None
        assert column["nullable"] is True
        # Float maps to PG double precision; assert the runtime type is real-valued.
        assert "DOUBLE PRECISION" in str(column["type"]).upper()

        command.downgrade(_alembic_config(), "0024")
        assert _effective_sources_column(engine) is None

        command.upgrade(_alembic_config(), "head")
        assert _effective_sources_column(engine) is not None
    finally:
        engine.dispose()
