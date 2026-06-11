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
