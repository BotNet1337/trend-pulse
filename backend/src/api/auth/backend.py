"""Authentication backend — JWT strategy over an httpOnly cookie transport.

We configure (never implement) the fastapi-users JWT + cookie auth backend:
- `CookieTransport`: httpOnly + Secure + SameSite=lax cookie for the SPA.
- `JWTStrategy`: signs the access token with `jwt_secret`, TTL `jwt_lifetime_seconds`.
The `FastAPIUsers` instance and the reusable `current_user` dependency are built
here and re-exported via the package `__init__`.
"""

from fastapi_users import FastAPIUsers
from fastapi_users.authentication import (
    AuthenticationBackend,
    CookieTransport,
    JWTStrategy,
)

from api.auth.users import get_user_manager
from config import Settings, get_settings
from storage.models.users import User

# httpOnly so JS can't read it (XSS), Secure (HTTPS-only) in prod, SameSite=lax to
# blunt CSRF while allowing top-level navigation (OAuth redirect flow). `cookie_secure`
# comes from settings: True on prod (HTTPS), False for local http dev (task-001 serves
# :80 only) — otherwise the browser/curl never returns the Secure cookie over http.
cookie_transport = CookieTransport(
    cookie_max_age=get_settings().jwt_lifetime_seconds,
    cookie_secure=get_settings().auth_cookie_secure,
    cookie_httponly=True,
    cookie_samesite="lax",
)


def build_jwt_strategy(settings: Settings | None = None) -> JWTStrategy[User, int]:
    """Construct the JWT strategy from settings (secret + TTL, never hardcoded)."""
    cfg = settings if settings is not None else get_settings()
    return JWTStrategy(secret=cfg.jwt_secret, lifetime_seconds=cfg.jwt_lifetime_seconds)


def get_jwt_strategy() -> JWTStrategy[User, int]:
    """fastapi-users `get_strategy` callable for the auth backend."""
    return build_jwt_strategy()


auth_backend: AuthenticationBackend[User, int] = AuthenticationBackend(
    name="jwt",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, int](get_user_manager, [auth_backend])

# Reusable dependency that all user-facing routes depend on (ADR-002 tenant scope).
current_user = fastapi_users.current_user(active=True)

# Superuser-gated dependency for ops / admin endpoints (TASK-051).
# Returns 401 if unauthenticated, 403 if authenticated but not a superuser.
current_superuser = fastapi_users.current_user(active=True, superuser=True)
