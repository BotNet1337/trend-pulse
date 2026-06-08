"""Shared pytest fixtures for the trendpulse backend test suite.

The `db_session` fixture is gated behind the `integration` marker: it connects to
a live pgvector Postgres (via `Settings.database_url`), applies the schema, yields
a session, and tears it down. Unit tests (`-m 'not integration'`, used by
`make ci-fast`) never touch it, so they need no DB.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from trendpulse.config import get_settings
from trendpulse.storage.models import Base


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """Engine bound to the live test DB; ensures `vector` ext + schema exist."""
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    with engine.begin() as conn:
        # Defensive: provisioner installs this in real infra; create for fixtures.
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """A clean session per test; truncates all tables on teardown."""
    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        # Wipe all rows so tests stay isolated (delete children before parents).
        with db_engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())
