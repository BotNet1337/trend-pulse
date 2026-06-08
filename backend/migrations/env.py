"""Alembic migration environment (SQLAlchemy 2.0).

DB URL comes from the environment via `trendpulse.config.Settings`, never the ini.
`target_metadata` will reference the ORM `Base.metadata` once the data model lands
(task-002); for task-001 it is `None` (no autogenerate target yet).
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection

from trendpulse.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the runtime DB URL (env-sourced) so the ini stays credential-free.
config.set_main_option("sqlalchemy.url", get_settings().database_url)

# No ORM metadata yet — set by task-002 (e.g. `from trendpulse.storage import Base`).
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (emit SQL)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    section = config.get_section(config.config_ini_section, {})
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
