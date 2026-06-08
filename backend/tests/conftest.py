"""Shared pytest fixtures for the trendpulse backend test suite.

The `db_session` fixture is gated behind the `integration` marker: it connects to
a live pgvector Postgres (via `Settings.database_url`), applies the schema, yields
a session, and tears it down. Unit tests (`-m 'not integration'`, used by
`make ci-fast`) never touch it, so they need no DB.
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

# Auth secrets have NO source default (AC6: fail-fast in prod). Seed test-only
# dummies BEFORE any module imports `get_settings()`, so the suite (and
# `make ci-fast`) runs without a real sensitive.env. `setdefault` never clobbers a
# value the AC6 test deletes via monkeypatch.delenv.
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("OAUTH_STATE_SECRET", "test-oauth-state-secret")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-google-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-google-client-secret")
# TestClient talks plain http → a Secure cookie would never be sent back, so the
# auth flow test uses a non-Secure cookie (mirrors local dev; prod stays True).
os.environ.setdefault("AUTH_COOKIE_SECURE", "false")

from config import get_settings
from storage.models import Base


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
