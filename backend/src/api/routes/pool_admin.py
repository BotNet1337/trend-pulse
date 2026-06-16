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
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated, Final, Protocol, cast

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from api.auth import current_superuser
from collector.constants import (
    POOL_HEALTH_REDIS_KEY,
    POOL_MAX,
    POOL_REVIVE_SIGNAL_REDIS_KEY,
    POOL_REVIVE_SIGNAL_TTL_SECONDS,
    QUARANTINE_REDIS_KEY,
)
from collector.errors import (
    PoolCapacityExceededError,
    QRLoginCapacityError,
    QRLoginNotConfiguredError,
)
from collector.telegram.account_pool import session_fingerprint
from collector.telegram.qr_login import QRLoginPoll, QRLoginService, QRLoginStatus
from config import Settings, get_settings, telegram_pool_sessions
from storage.database import get_session
from storage.models.users import User
from storage.pool_session_store import ReviveOutcome, UpsertResult, upsert_revive_or_add

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
# Clear, non-secret message when an ADD would exceed the pool capacity (TASK-120). The
# admin must revoke an account first; a revive (existing account) never trips this.
_POOL_FULL_MESSAGE: Final = "The pool is full — revoke an existing account before adding a new one."


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


class _ReviveRedisLike(Protocol):
    """Minimal Redis WRITE surface the revive-signal path uses (TASK-120).

    `set` writes the NON-SECRET revive-signal (TTL); `srem` clears the OLD quarantine
    fingerprint on a REVIVE. `close` tears the short-lived client down. Both a concrete
    `Redis` and `fakeredis.FakeRedis(decode_responses=True)` satisfy this; the route
    never puts a secret through any of them.
    """

    def set(self, name: str, value: str, *, ex: int) -> object: ...

    def srem(self, name: str, *values: str) -> int: ...

    def close(self) -> None: ...


class _ReviveRedisAdapter:
    """Adapt a concrete `Redis` (decode_responses=True) to `_ReviveRedisLike`.

    Pins redis-py's `Awaitable[...] | Any` stubs to concrete sync results with one
    `cast` each at this single typed seam — no `Any` / `# type: ignore` leaks past it
    (mirrors `_RedisAdapter`). The revive-signal value + the fingerprint are non-secret.
    """

    def __init__(self, client: Redis) -> None:
        self._client = client

    def set(self, name: str, value: str, *, ex: int) -> object:
        return self._client.set(name, value, ex=ex)

    def srem(self, name: str, *values: str) -> int:
        return cast("int", self._client.srem(name, *values))

    def close(self) -> None:
        try:
            self._client.close()
        except Exception as exc:
            logger.warning("pool-revive redis close failed: %s", type(exc).__name__)


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
        # Best-effort teardown: a close() that raises on an already-broken socket
        # must NEVER mask the in-flight response (e.g. replace a 503 with a 500).
        # Swallow + log the exception TYPE only (no DSN/secret) — mirrors
        # `api.routes.ops._check_redis`.
        try:
            self._client.close()
        except Exception as exc:
            logger.warning("pool-health redis close failed: %s", type(exc).__name__)


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
    # SECRET: the minted session string — present only on success, never logged. Kept as
    # the disaster-recovery floor (the admin can still copy it to the vault); automatic
    # persistence (TASK-120) happens on top of it.
    session_string: str | None = None
    # Non-secret human reason on password_needed / error (exception class name).
    reason: str | None = None
    # NON-SECRET account identity from `get_me()` (TASK-119/120), present only on SUCCESS:
    # `tg_user_id` is the account's public numeric id (the revive/add upsert key) and
    # `display_label` is a masked id / `@username` for the UI. Neither is a secret.
    tg_user_id: int | None = None
    display_label: str | None = None
    # Whether the persisted store REVIVED an existing account ("revive") or ADDED a new
    # one ("add") — present only on SUCCESS (TASK-120). Lets the UI say "re-connected" vs
    # "added". None when persistence was not attempted / not reached.
    outcome: str | None = None


class PoolHealthAccount(BaseModel):
    """One pool account's health, with optional NON-SECRET identity (TASK-120).

    `index` is the stable per-slot identifier; `display_label`/`tg_user_id` are the
    NON-SECRET store identity (masked id / `@username` / numeric id) when the slot was
    loaded from the dynamic store, else null (an env-only slot). NEVER a session string.
    """

    model_config = ConfigDict(extra="forbid")

    index: int
    state: str  # "healthy" | "cooling" | "quarantined" | "failing"
    cooldown_remaining_seconds: float | None = None
    last_error_reason: str = ""
    # NON-SECRET per-account identity (TASK-120): null for an env-only / pre-identity slot.
    display_label: str | None = None
    tg_user_id: int | None = None


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
    # Derived "all-healthy-but-ingest-stale" contradiction (TASK-118): true when every
    # account is healthy yet ingest is stale (the "all green but 0 posts" signal). Default
    # false (fail-open) so an old snapshot or a missing flag never raises a false alarm.
    ingest_contradiction: bool = False


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
    # Additive (TASK-118); default false so an older snapshot without the field validates.
    ingest_contradiction: bool = False


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


def get_pool_admin_db() -> Iterator[Session]:
    """Yield a sync DB session (unit-of-work) for the persist-on-success path (TASK-120).

    The store (`upsert_revive_or_add`) is sync and runs in a threadpool; this short-lived
    session commits on success / rolls back on error (mirrors `api.watchlist.deps`).
    Tests override this dependency to point at the shared test schema.
    """
    with get_session() as session:
        yield session


def get_pool_revive_redis() -> Iterator[_ReviveRedisLike]:
    """Yield a short-lived Redis client for the NON-SECRET revive-signal write (TASK-120).

    On a REVIVE the route writes the revive-signal (the affected slot's identity only,
    never a secret) so the worker swaps the live slot on its next tick, and clears the
    OLD fingerprint's persisted quarantine. Mirrors `get_pool_health_redis`: bounded
    socket timeouts, `decode_responses=True`, behind the narrow `_ReviveRedisLike`. The
    client is closed after the request (the `finally` teardown never masks the response).
    """
    settings = get_settings()
    client = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=settings.readiness_check_timeout_seconds,
        socket_timeout=settings.readiness_check_timeout_seconds,
        decode_responses=True,
    )
    adapter = _ReviveRedisAdapter(client)
    try:
        yield adapter
    finally:
        adapter.close()


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
    db: Annotated[Session, Depends(get_pool_admin_db)],
    revive_redis: Annotated[_ReviveRedisLike, Depends(get_pool_revive_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> QRLoginPollResponse:
    """Poll an in-progress login; on SUCCESS persist + classify (TASK-119/120).

    Reflects `service.poll()`: unknown/expired tokens return status `expired`
    (200, never 404/500 — the UI polls in a loop). On SUCCESS the body carries the
    minted `session_string` (secret, never logged) AND, when the poll yields an
    account identity, the route PERSISTS the session via the dynamic store
    (`upsert_revive_or_add`, idempotent by `tg_user_id`), writes the NON-SECRET
    revive-signal on a REVIVE so the worker swaps the live slot, and returns the
    non-secret identity + outcome ("revive"/"add").

    A persistence/DB failure does NOT drop the minted `session_string`: it is still
    returned as the disaster-recovery floor (the admin can paste it into the vault),
    and the failure surfaces as a clear envelope only when the pool is over capacity.
    """
    poll = await service.poll(token)

    response = QRLoginPollResponse(
        status=poll.status.value,
        expires_at=poll.expires_at,
        session_string=poll.session_string,
        reason=poll.reason,
        tg_user_id=poll.tg_user_id,
        display_label=poll.display_label,
    )

    # Persist + classify only on a SUCCESS that carries a full identity (a success
    # without identity should never happen — qr_login surfaces ERROR if get_me() fails —
    # but guard so a partial result can never crash the route).
    if (
        poll.status is QRLoginStatus.SUCCESS
        and poll.session_string is not None
        and poll.tg_user_id is not None
        and poll.display_label is not None
    ):
        return await _persist_qr_success(poll, response, db, revive_redis, settings)
    return response


async def _persist_qr_success(
    poll: QRLoginPoll,
    response: QRLoginPollResponse,
    db: Session,
    revive_redis: _ReviveRedisLike,
    settings: Settings,
) -> QRLoginPollResponse:
    """Persist a SUCCESS poll via the store and return identity + outcome (TASK-120).

    The store decides REVIVE (existing `tg_user_id`) vs ADD (new) and is idempotent, so a
    repeated SUCCESS poll never creates a duplicate or re-fires harm. On a REVIVE the
    NON-SECRET revive-signal is written (the worker swaps the live slot next tick) and the
    OLD fingerprint's persisted quarantine is cleared. An over-capacity ADD maps to a clear
    409. ANY other store/DB error keeps the `session_string` copy-field (DR floor) — the
    error is logged (class name only) and the response is returned without an `outcome`.
    """
    assert poll.tg_user_id is not None  # narrowed by the caller
    assert poll.session_string is not None
    assert poll.display_label is not None
    env_floor_size = len(set(telegram_pool_sessions(settings)))
    try:
        result: UpsertResult = await run_in_threadpool(
            upsert_revive_or_add,
            db,
            tg_user_id=poll.tg_user_id,
            session_string=poll.session_string,
            display_label=poll.display_label,
            pool_max=POOL_MAX,
            env_floor_size=env_floor_size,
        )
    except PoolCapacityExceededError:
        # The minted session is still handed back (DR floor) BUT the body is a 409 so the
        # UI can say "pool is full — revoke an account first" (no 500). The session string
        # is NOT lost: the admin can still copy it to the vault. No secret in the message.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_POOL_FULL_MESSAGE,
        ) from None
    except Exception as exc:
        # DR-floor preservation: a store/DB error must NOT lose the minted session. The store
        # FLUSHES, so a flush-level failure leaves the Session in a failed-transaction state;
        # without a rollback here, `get_session`'s teardown commit() would raise
        # PendingRollbackError → a 500 that LOSES the session_string this branch exists to
        # protect. Roll back first (mirrors api.watchlist.service), THEN return the copy-field
        # (no outcome) so the admin can still vault it. Log class name only — never the secret.
        db.rollback()
        logger.warning(
            "pool session persist on QR success failed (session copy-field preserved): %s",
            type(exc).__name__,
            extra={
                "tg_user_id": poll.tg_user_id,
                "fingerprint": session_fingerprint(poll.session_string),
            },
        )
        return response

    if result.outcome is ReviveOutcome.REVIVE:
        _signal_revive(revive_redis, result)
    return response.model_copy(update={"outcome": result.outcome.value})


def _signal_revive(revive_redis: _ReviveRedisLike, result: UpsertResult) -> None:
    """Write the NON-SECRET revive-signal + clear the OLD quarantine (best-effort).

    The worker applies the live single-slot swap on its next tick (TASK-119). Both writes
    are best-effort/fail-open: a Redis error is logged (class name only) and swallowed —
    a missed signal self-heals on the next full pool build, and the persisted row is the
    source of truth. NEVER a secret: the signal carries only the slot identity + fp.
    """
    payload = json.dumps({"tg_user_id": result.tg_user_id, "fingerprint": result.fingerprint})
    try:
        revive_redis.set(POOL_REVIVE_SIGNAL_REDIS_KEY, payload, ex=POOL_REVIVE_SIGNAL_TTL_SECONDS)
    except RedisError as exc:
        logger.warning("could not write pool revive signal (Redis): %s", type(exc).__name__)
    if result.previous_fingerprint:
        try:
            revive_redis.srem(QUARANTINE_REDIS_KEY, result.previous_fingerprint)
        except RedisError as exc:
            logger.warning(
                "could not clear old quarantine fingerprint on revive (Redis): %s",
                type(exc).__name__,
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
        # Teardown must NEVER mask the in-flight response (e.g. turn a 503 into a
        # 500). Guard at the call site so it holds for ANY `_RedisLike` impl, not
        # only the self-guarding `_RedisAdapter`. Log the type only (no DSN/secret).
        try:
            redis.close()
        except Exception as exc:
            logger.warning("pool-health redis close failed: %s", type(exc).__name__)

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
        ingest_contradiction=snapshot.ingest_contradiction,
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
    "get_pool_admin_db",
    "get_pool_health_redis",
    "get_pool_revive_redis",
    "get_qr_login_service",
    "router",
]
