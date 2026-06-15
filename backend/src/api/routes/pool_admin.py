"""Superuser pool-admin router (TASK-116, EPIC-TG-QR-POOL).

Three superuser-gated endpoints that wire the TASK-114 QR-login service and the
TASK-115 pool-health Redis snapshot to the frontend (TASK-117 consumes this):

  * `POST /pool-admin/qr-login/start` — begin a QR login, return the deep link.
  * `GET  /pool-admin/qr-login/{token}` — poll an in-progress login.
  * `GET  /pool-admin/pool-health` — read the latest pool-health snapshot.

Invariants (CONVENTIONS + the task doc):
  * Every route depends on `current_superuser` (401 unauthenticated, 403 non-admin).
  * Pydantic models validate the boundary (`extra="forbid"`); the minted
    `session_string` is the whole point of the QR flow (admin copies it to the
    vault) but is NEVER logged — this router does not log request/response bodies.
  * The QR service is a PROCESS-SINGLETON built from settings (matches the
    in-process registry design from TASK-114): one live registry per uvicorn worker.
  * Failures map to the unified envelope via plain `HTTPException` (api.main maps
    status → ErrorCode): missing creds → 503, capacity → 429, unknown token → an
    `expired` poll status (200, not a 404 storm from UI polling).
  * Redis unreachable / snapshot absent or old → `stale=true` (never an unhandled
    500); a hard Redis failure surfaces as 503, again via the envelope.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Annotated, Final, Protocol, cast

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis import Redis
from redis.exceptions import RedisError

from api.auth import current_superuser
from collector.constants import POOL_HEALTH_REDIS_KEY
from collector.errors import QRLoginCapacityError, QRLoginNotConfiguredError
from collector.telegram.qr_login import QRLoginService, QRLoginStatus
from config import Settings, get_settings
from storage.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pool-admin", tags=["pool-admin"])

# Staleness threshold for the pool-health badge. The snapshot's own Redis key TTL
# is 300s (TASK-115), so any present snapshot is at most ~5min old; the API uses a
# tighter "fresh vs stale" threshold of 2x the collect cadence — a snapshot older
# than two missed ticks means the collector is lagging/down.
_STALENESS_MULTIPLE: Final = 2

# Clear, non-secret message surfaced when QR-login creds are not configured. No
# stack/secret leak (the underlying error carries only a generic deployment hint).
_QR_NOT_CONFIGURED_MESSAGE: Final = (
    "QR login is not configured (telegram_api_id / telegram_api_hash missing)."
)
_QR_CAPACITY_MESSAGE: Final = "Too many concurrent QR logins in progress. Retry shortly."
_POOL_HEALTH_REDIS_UNREACHABLE_MESSAGE: Final = "Pool-health store is unreachable."


class _RedisLike(Protocol):
    """Minimal Redis read surface this router uses (sync redis-py / fakeredis).

    redis-py's stubs type `get`/`close` as `Awaitable[...] | ...` unions; pinning a
    narrow protocol here (a `str | None` `get` under `decode_responses=True`) keeps
    mypy strict-green without `cast`/`# type: ignore`, and both a concrete `Redis`
    client and `fakeredis.FakeRedis(decode_responses=True)` satisfy it (mirrors
    `collector.buffer._RedisLike`).
    """

    def get(self, name: str) -> str | None: ...

    def close(self) -> None: ...


class _RedisAdapter:
    """Adapts a concrete `Redis` (decode_responses=True) to `_RedisLike`.

    redis-py's `get`/`close` are stubbed as `Awaitable[...] | Any` unions; this
    single typed seam pins the sync `str | None` / `None` results with one `cast`
    each — no `Any` and no `# type: ignore` leak past this boundary (mirrors
    `collector.telegram.qr_login._RealClientAdapter`).
    """

    def __init__(self, client: Redis) -> None:
        self._client = client

    def get(self, name: str) -> str | None:
        return cast("str | None", self._client.get(name))

    def close(self) -> None:
        self._client.close()


# ---------------------------------------------------------------------------
# Pydantic response models (boundary — extra="forbid")
# ---------------------------------------------------------------------------


class QRLoginStartResponse(BaseModel):
    """`POST /pool-admin/qr-login/start` body — the QR deep link + expiry."""

    model_config = ConfigDict(extra="forbid")

    token: str
    # `tg://login?token=...` deep link the frontend renders as a QR code.
    qr_url: str
    expires_at: float  # epoch seconds (wall clock)
    timeout_seconds: int


class QRLoginPollResponse(BaseModel):
    """`GET /pool-admin/qr-login/{token}` body — the current login state.

    `session_string` is the NEWLY minted StringSession, present ONLY on SUCCESS.
    It is a SECRET (the admin copies it to the vault); it is never logged and is
    served only to a superuser over HTTPS.
    """

    model_config = ConfigDict(extra="forbid")

    status: str  # one of QRLoginStatus values: pending/success/expired/password_needed/error
    expires_at: float
    # SECRET: the minted session string — present only on success, never logged.
    session_string: str | None = None
    # Non-secret human reason on password_needed / error (exception class name).
    reason: str | None = None


class PoolHealthAccount(BaseModel):
    """One pool account's health (per-account identity is the integer index only)."""

    model_config = ConfigDict(extra="forbid")

    index: int
    state: str  # "healthy" | "cooling" | "quarantined"
    cooldown_remaining_seconds: float | None = None
    last_error_reason: str = ""


class PoolHealthResponse(BaseModel):
    """`GET /pool-admin/pool-health` body — aggregates + per-account list + staleness.

    `stale` is true when the snapshot is missing/old (collector down or lagging);
    in that case the aggregates are zeroed and `accounts` is empty so the UI can
    say "no fresh data from collector" without erroring.
    """

    model_config = ConfigDict(extra="forbid")

    size: int = 0
    cooling: int = 0
    quarantined: int = 0
    healthy: int = 0
    target: int = 0
    degraded: bool = False
    # UTC ISO-8601 timestamp of the snapshot; None when no snapshot exists.
    as_of: str | None = None
    stale: bool = True
    accounts: list[PoolHealthAccount] = Field(default_factory=list)


class _PoolHealthSnapshot(BaseModel):
    """System-boundary validator for the raw `pool:health:latest` JSON (TASK-115).

    Mirrors the writer's schema exactly; `extra="ignore"` so a forward-compatible
    field added by a newer collector does not reject the whole snapshot.
    """

    model_config = ConfigDict(extra="ignore")

    size: int
    cooling: int
    quarantined: int
    healthy: int
    target: int
    degraded: bool
    as_of: str
    accounts: list[PoolHealthAccount]


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

# Process-singleton QR-login service (TASK-114 in-process registry: one live
# registry of in-progress logins per uvicorn worker). Built lazily on first use
# from settings so importing this module never requires telethon / creds.
_qr_login_service: QRLoginService | None = None


def get_qr_login_service() -> QRLoginService:
    """Return the process-singleton `QRLoginService`, building it on first call.

    One instance per process (the registry holds live connected clients keyed by
    opaque token). Creds may be absent — the service is still constructable and
    `start()` raises `QRLoginNotConfiguredError`, mapped to a 503 by the route.
    """
    global _qr_login_service
    if _qr_login_service is None:
        settings = get_settings()
        _qr_login_service = QRLoginService.from_settings_values(
            api_id=settings.telegram_api_id,
            api_hash=settings.telegram_api_hash,
            timeout_seconds=settings.qr_login_timeout_seconds,
        )
    return _qr_login_service


def get_pool_health_redis() -> _RedisLike:
    """Return a short-lived Redis client bounded by the readiness timeout.

    Mirrors `routes/ops.py`: socket timeouts so a stalled (not refused) Redis can
    never hang the request. `decode_responses=True` so `get()` yields a `str`. The
    concrete `Redis` is returned behind the narrow `_RedisLike` protocol.
    """
    settings = get_settings()
    client = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=settings.readiness_check_timeout_seconds,
        socket_timeout=settings.readiness_check_timeout_seconds,
        decode_responses=True,
    )
    return _RedisAdapter(client)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/qr-login/start",
    response_model=QRLoginStartResponse,
    summary="Begin a QR login (superuser only)",
)
async def start_qr_login(
    _user: Annotated[User, Depends(current_superuser)],
    service: Annotated[QRLoginService, Depends(get_qr_login_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> QRLoginStartResponse:
    """Start a QR login and return the deep link + token.

    Auth: 401 unauthenticated, 403 non-superuser. Maps service raise-paths:
    missing creds → 503, registry at capacity → 429. No secrets logged.
    """
    try:
        started = await service.start()
    except QRLoginNotConfiguredError:
        # No stack/secret leak — only the generic deployment hint.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_QR_NOT_CONFIGURED_MESSAGE,
        ) from None
    except QRLoginCapacityError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=_QR_CAPACITY_MESSAGE,
        ) from None
    return QRLoginStartResponse(
        token=started.token,
        qr_url=started.qr_url,
        expires_at=started.expires_at,
        timeout_seconds=settings.qr_login_timeout_seconds,
    )


@router.get(
    "/qr-login/{token}",
    response_model=QRLoginPollResponse,
    summary="Poll a QR login (superuser only)",
)
async def poll_qr_login(
    token: str,
    _user: Annotated[User, Depends(current_superuser)],
    service: Annotated[QRLoginService, Depends(get_qr_login_service)],
) -> QRLoginPollResponse:
    """Poll an in-progress login.

    Reflects `service.poll()`: unknown/expired tokens return status `expired`
    (200, never 404/500 — the UI polls in a loop). On SUCCESS the body carries the
    minted `session_string` (secret, never logged).
    """
    poll = await service.poll(token)
    return QRLoginPollResponse(
        status=poll.status.value,
        expires_at=poll.expires_at,
        session_string=poll.session_string,
        reason=poll.reason,
    )


@router.get(
    "/pool-health",
    response_model=PoolHealthResponse,
    summary="Latest pool-health snapshot (superuser only)",
)
def get_pool_health(
    _user: Annotated[User, Depends(current_superuser)],
    redis: Annotated[_RedisLike, Depends(get_pool_health_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PoolHealthResponse:
    """Read the latest `pool:health:latest` snapshot from Redis.

    Missing/old snapshot (collector down ≥ TTL, or lagging) → `stale=true` with
    empty aggregates. Redis unreachable → 503 envelope (not an unhandled 500).
    A parse/validation failure of a present snapshot is treated as stale.
    """
    try:
        raw = redis.get(POOL_HEALTH_REDIS_KEY)
    except RedisError:
        # Reading is impossible — surface a clear 503 (no DSN/exception leak).
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_POOL_HEALTH_REDIS_UNREACHABLE_MESSAGE,
        ) from None
    finally:
        redis.close()

    if raw is None:
        # No recent snapshot (worker down ≥ TTL, or never ran).
        return PoolHealthResponse(stale=True)

    try:
        snapshot = _PoolHealthSnapshot.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError):
        # A malformed snapshot is treated as no fresh data (never an unhandled 500).
        logger.warning("pool-health snapshot failed to parse/validate; treating as stale")
        return PoolHealthResponse(stale=True)

    stale = _is_stale(snapshot.as_of, settings.collect_interval_seconds)
    return PoolHealthResponse(
        size=snapshot.size,
        cooling=snapshot.cooling,
        quarantined=snapshot.quarantined,
        healthy=snapshot.healthy,
        target=snapshot.target,
        degraded=snapshot.degraded,
        as_of=snapshot.as_of,
        stale=stale,
        accounts=snapshot.accounts,
    )


def _is_stale(as_of: str, collect_interval_seconds: int) -> bool:
    """True when the snapshot is older than `_STALENESS_MULTIPLE` collect ticks.

    A snapshot whose `as_of` can't be parsed is treated as stale (defensive: the
    badge should fail closed rather than claim fresh data).
    """
    try:
        as_of_dt = datetime.fromisoformat(as_of)
    except ValueError:
        return True
    if as_of_dt.tzinfo is None:
        as_of_dt = as_of_dt.replace(tzinfo=UTC)
    age_seconds = (datetime.now(UTC) - as_of_dt).total_seconds()
    return age_seconds > _STALENESS_MULTIPLE * collect_interval_seconds


# Re-exported so callers/tests can map poll statuses without importing the service.
__all__ = [
    "PoolHealthResponse",
    "QRLoginPollResponse",
    "QRLoginStartResponse",
    "QRLoginStatus",
    "get_pool_health_redis",
    "get_qr_login_service",
    "router",
]
