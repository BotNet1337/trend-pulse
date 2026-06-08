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

from trendpulse.config import get_settings

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
        _drop_statements = (
            "DROP TABLE IF EXISTS alerts CASCADE",
            "DROP TABLE IF EXISTS scores CASCADE",
            "DROP TABLE IF EXISTS clusters CASCADE",
            "DROP TABLE IF EXISTS posts CASCADE",
            "DROP TABLE IF EXISTS watchlists CASCADE",
            "DROP TABLE IF EXISTS channels CASCADE",
            "DROP TABLE IF EXISTS users CASCADE",
            "DROP TABLE IF EXISTS alembic_version",
        )
        with engine.begin() as conn:
            for stmt in _drop_statements:
                conn.execute(text(stmt))

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
        assert current == _BASELINE_REVISION
        assert head == _BASELINE_REVISION
    finally:
        engine.dispose()
