"""Sync engine + session factory (SQLAlchemy 2.0 + psycopg).

Sync is intentional for the storage/repository layer (migrations + repos
round-trip). The fastapi-users SQLAlchemy adapter, however, is async-only, so an
**async** engine/session factory is also exposed here (same `psycopg` v3 driver,
async mode) for `api/auth/` to depend on. Both share `Settings.database_url`.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from config import get_settings

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


def _build_async_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=_POOL_PRE_PING)


async_engine: AsyncEngine = _build_async_engine()
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=async_engine, autoflush=False, expire_on_commit=False
)


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield an `AsyncSession` (used by the auth user-db)."""
    async with AsyncSessionLocal() as session:
        yield session
