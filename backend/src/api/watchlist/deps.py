"""Sync DB-session dependency for the watchlist routes.

The repositories are SYNC (storage/), so the route handlers are sync `def` and run
in FastAPI's threadpool (the async `current_user` dependency still resolves). This
wraps the sync `get_session` contextmanager (commit-on-success, rollback-on-error)
as a FastAPI dependency, and is overridden in tests to share the test session.
"""

from collections.abc import Iterator

from sqlalchemy.orm import Session

from storage.database import get_session


def get_db_session() -> Iterator[Session]:
    """Yield a committing sync session for one request (see `storage.get_session`)."""
    with get_session() as session:
        yield session
