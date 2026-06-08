"""Sync engine + session factory (SQLAlchemy 2.0 + psycopg).

Sync is intentional for this layer (migrations + repos round-trip); async sessions
are introduced separately if a later task needs them (task-002 Discussion).
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from trendpulse.config import get_settings

_POOL_PRE_PING = True


def _build_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=_POOL_PRE_PING)


engine: Engine = _build_engine()
SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False
)


@contextmanager
def get_session() -> Iterator[Session]:
    """Yield a session, committing on success and rolling back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
