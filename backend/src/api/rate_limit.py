"""API rate limiting (task-011, overview §7) — slowapi, Redis-backed.

Per-key request budget (default `RATE_LIMIT_PER_MINUTE`), where the key is:
  1. `apikey:<sha256[:16]>` when an X-API-Key header is present (TASK-028, no DB);
  2. `user:<id>` when an authenticated JWT/cookie is present (no DB);
  3. `ip:<addr>` for anonymous traffic.

Keying by api-key principal (not IP) ensures one tenant's key does not exhaust
another's budget behind NAT/proxy.  The sha256 truncation (16 chars) avoids
logging the full key material in slowapi's Redis key while keeping the key space
collision-free for practical purposes.

Exceeding the limit raises `RateLimitExceeded`, mapped by `rate_limit_handler` to
a clear `429` JSON body. The default limit string is built from settings (no magic
literal). slowapi degrades by RAISING if Redis is unreachable rather than failing
open silently (edge case: we do not mask a broken limiter).
"""

import hashlib

import jwt
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.status import HTTP_429_TOO_MANY_REQUESTS

from api.auth.backend import cookie_transport
from api.errors import ErrorCode, build_error_response
from config import get_settings

# fastapi-users JWTStrategy defaults (api/auth/backend.py): HS256 + this audience.
_JWT_ALGORITHM = "HS256"
_JWT_AUDIENCE = ["fastapi-users:auth"]

# Prefix length for per-apikey rate-limit key derivation (no DB; hash truncation).
_APIKEY_HASH_PREFIX_LEN = 16
_X_API_KEY_HEADER = "x-api-key"


def _resolve_user_id(request: Request) -> str | None:
    """Best-effort authenticated user id for rate-limit keying — no DB hit.

    Reads the fastapi-users auth cookie (or a Bearer token) and decodes the JWT
    with the server secret to extract `sub` (the user id). Pure token decode (no
    user lookup): a forged/expired/missing token yields None → IP keying. Cached on
    `request.state.user_id` so it is decoded at most once per request.
    """
    cached = getattr(request.state, "user_id", None)
    if cached is not None:
        return str(cached)
    token = request.cookies.get(cookie_transport.cookie_name)
    if token is None:
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else None
    if not token:
        return None
    try:
        payload = jwt.decode(
            token,
            get_settings().jwt_secret,
            audience=_JWT_AUDIENCE,
            algorithms=[_JWT_ALGORITHM],
        )
    except jwt.PyJWTError:
        return None  # invalid/expired/forged → anonymous (IP keyed)
    sub = payload.get("sub")
    if sub is None:
        return None
    request.state.user_id = str(sub)
    return str(sub)


def rate_limit_key(request: Request) -> str:
    """Key requests by principal: api-key > user-id > client IP.

    Priority:
    1. X-API-Key header present → `apikey:<sha256[:16]>` (no DB, per-key bucket).
       The sha256 hash avoids including raw key material in Redis key names while
       still giving a per-key limit (collision-free for practical purposes).
    2. Authenticated JWT/cookie → `user:<id>` (decoded, no DB).
    3. Anonymous → `ip:<addr>`.

    Prefixes keep the three key spaces from colliding.
    """
    # Priority 1: X-API-Key header (TASK-028 — per-key bucket, no DB).
    api_key_value = request.headers.get(_X_API_KEY_HEADER)
    if api_key_value:
        key_digest = hashlib.sha256(api_key_value.encode()).hexdigest()
        return f"apikey:{key_digest[:_APIKEY_HASH_PREFIX_LEN]}"

    # Priority 2: JWT/cookie user id.
    user_id = _resolve_user_id(request)
    if user_id is not None:
        return f"user:{user_id}"

    return f"ip:{get_remote_address(request)}"


def default_limit() -> str:
    """The default per-key limit string (e.g. "120/minute") from settings."""
    return f"{get_settings().rate_limit_per_minute}/minute"


def build_limiter() -> Limiter:
    """Construct the Redis-backed limiter with the configured default limit.

    `in_memory_fallback_enabled` is the documented Redis-down behaviour (edge case):
    if the Redis store is unreachable, slowapi falls back to an in-process limiter
    (logging the switch) and KEEPS enforcing the same limit rather than crashing
    every request or silently failing open. The limit is still enforced; only its
    scope degrades from cross-replica to per-process until Redis returns.
    """
    return Limiter(
        key_func=rate_limit_key,
        default_limits=[default_limit()],
        storage_uri=get_settings().redis_url,
        in_memory_fallback=[default_limit()],
        in_memory_fallback_enabled=True,
    )


# Module-level singleton: `api.main` registers it on the app + exception handler,
# and routes reference it for per-route overrides if needed.
limiter = build_limiter()


def rate_limit_handler(_: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Map a rate-limit breach to the unified 429 envelope (no internal leakage)."""
    return build_error_response(
        code=ErrorCode.RATE_LIMITED,
        message="Rate limit exceeded. Please slow down.",
        status=HTTP_429_TOO_MANY_REQUESTS,
    )
