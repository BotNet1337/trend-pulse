"""X-API-Key authentication backend — parallel to cookie/JWT (TASK-028).

`current_user_or_api_key` is a combined dependency for READ-ONLY routes
(alerts/watchlists).  Priority: cookie/JWT first (existing UI flow unaffected),
then X-API-Key header (programmatic access).  If neither is present/valid → 401.

Security notes:
- The `resolve_api_key` DB call runs in FastAPI's threadpool via `run_in_threadpool`
  (the route handlers that use this dep are sync; the dep itself is async to compose
  with fastapi-users' async current_user optional variant).
- `X-API-Key` access is NEVER recursive: the endpoint at POST /api-keys uses plain
  `current_user` (cookie-only), so an API key cannot create or revoke other keys.
- Error response is generic 401 without revealing whether the key was unknown,
  revoked, or the user is on the wrong plan (no oracle).

Circular-import note: this module must NOT import from api.watchlist (that package
imports this module back). Instead we declare our own `_get_db_session` that mirrors
api.watchlist.deps.get_db_session — same storage.database.get_session source.
Both are FastAPI Depends, so overriding `get_db_session` in tests overrides both.
"""

from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from api.auth.backend import fastapi_users
from storage.database import get_session
from storage.models.users import User

# Optional cookie/JWT user (does NOT raise if no cookie present).
_optional_cookie_user = fastapi_users.current_user(active=True, optional=True)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="not authenticated",
)


def _get_db_session() -> Iterator[Session]:
    """Sync DB session for the X-API-Key resolve path (mirrors api.watchlist.deps).

    Declared here to avoid the circular import chain:
    api.auth.api_key → api.watchlist.deps → api.watchlist → api.watchlist.router
    → api.auth.api_key.

    Tests that override `get_db_session` from `api.watchlist.deps` must also
    override this function if they need the session to be shared.  Integration
    test fixtures override both by importing `_get_db_session` directly.
    """
    with get_session() as session:
        yield session


async def current_user_or_api_key(
    cookie_user: User | None = Depends(_optional_cookie_user),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    session: Session = Depends(_get_db_session),
) -> User:
    """Resolve the request's user: cookie/JWT first, then X-API-Key header.

    Cookie-first means the UI (SPA) continues to work without changes. The
    X-API-Key path is for programmatic / server-to-server callers.

    Raises 401 if neither method yields a valid active user (generic message,
    no oracle for valid-vs-revoked-vs-wrong-plan distinction).
    """
    # Priority 1: existing cookie/JWT session (UI flow, no DB needed).
    if cookie_user is not None:
        return cookie_user

    # Priority 2: X-API-Key header — sync DB call via threadpool.
    if x_api_key is not None:
        from api.api_keys.service import resolve_api_key

        user: User | None = await run_in_threadpool(resolve_api_key, session, x_api_key)
        if user is not None:
            return user

    raise _UNAUTHORIZED
