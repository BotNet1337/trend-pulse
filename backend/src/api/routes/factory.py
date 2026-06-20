"""Superuser factory-admin router (TASK-135).

Four superuser-gated endpoints that expose the account-factory provisioning loop
to the admin UI:

  * ``POST /factory/accounts``        — trigger a factory tick (synchronous, in-proc).
  * ``GET  /factory/accounts``        — list all factory accounts across all states.
  * ``POST /factory/accounts/{id}/relogin`` — re-trigger provisioning for an account.
  * ``GET  /factory/budget``          — return budget math (budget/spent/remaining/enabled).

Invariants (CONVENTIONS + task doc):
  * Every route depends on ``current_superuser`` (401 unauthenticated, 403 non-admin).
  * ``session_string`` and ``proxy`` are NEVER included in any response model or log.
  * Pydantic response models validate the boundary (``extra="forbid"``).
  * Named constants for all user-facing messages (no magic literals).
  * Provider-driven activation: when ``settings.account_factory_provider`` is unset/empty,
    mutating endpoints return 503; read endpoints still return 200 with ``enabled=false``.
  * The tick runner is injected via ``get_factory_tick_runner()`` so tests can override it.
    The default runner calls ``run_factory_tick(redis, settings=settings)`` (``now`` defaults
    to ``None`` inside the tick).
  * Money is ``Decimal`` throughout (never float).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict
from redis import Redis
from sqlalchemy.orm import Session

from api.auth import current_superuser
from config import Settings, get_settings
from factory.constants import FACTORY_STATES
from factory.tasks import run_factory_tick
from storage import factory_account_store
from storage.database import get_session
from storage.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/factory", tags=["factory"])

# ---------------------------------------------------------------------------
# Named message constants (CONVENTIONS: no magic literals)
# ---------------------------------------------------------------------------

_FACTORY_NOT_CONFIGURED_MESSAGE: Final = (
    "Account factory is not configured (ACCOUNT_FACTORY_PROVIDER is unset or empty)."
)
_FACTORY_ACCOUNT_NOT_FOUND_MESSAGE: Final = "Factory account not found."

# ---------------------------------------------------------------------------
# Pydantic response models (boundary — extra="forbid")
# ---------------------------------------------------------------------------


class FactoryAccountOut(BaseModel):
    """`GET /factory/accounts` — a single factory account row.

    NEVER includes ``session_string`` or ``proxy`` — both are secrets. ``phone_masked``
    is already masked at rest and is safe to surface. ``tg_user_id`` is the public
    Telegram numeric id (non-secret identity), present only from the ``registered`` state.
    """

    model_config = ConfigDict(extra="forbid")

    id: int
    state: str
    phone_masked: str
    provider: str
    provider_order_id: str
    tg_user_id: int | None
    probation_until: str | None  # UTC ISO-8601, None when not set
    cost_usd: str  # Decimal serialised as string (never float)
    last_error: str | None
    created_at: str  # UTC ISO-8601
    updated_at: str  # UTC ISO-8601


class FactoryTriggerOut(BaseModel):
    """`POST /factory/accounts` — summary returned after triggering a tick (202)."""

    model_config = ConfigDict(extra="forbid")

    status: str  # "triggered"


class BudgetOut(BaseModel):
    """`GET /factory/budget` — budget math.

    ``budget_usd``/``spent_usd``/``remaining_usd`` are Decimal-serialised strings.
    ``provider`` is the configured slug (empty string when unset).
    ``enabled`` is True iff ``account_factory_provider`` is non-empty.
    """

    model_config = ConfigDict(extra="forbid")

    budget_usd: str  # Decimal as string
    spent_usd: str  # Decimal as string
    remaining_usd: str  # Decimal as string, always >= 0
    provider: str
    enabled: bool


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

# Type alias for the tick-runner callable that the route injects.
_TickRunner = Callable[[Redis, Settings], None]


def _default_tick_runner(redis: Redis, settings: Settings) -> None:
    """The real tick runner: delegates to ``run_factory_tick``.

    Separated so tests can override ``get_factory_tick_runner`` without importing
    the full factory dependency tree in test modules.
    """
    run_factory_tick(redis, settings=settings)


def get_factory_tick_runner() -> _TickRunner:
    """Return the factory tick runner callable.

    Tests override this dependency with a no-op or a fake that exercises the real
    ``run_factory_tick`` against fakeredis. The default implementation calls the
    real tick (opens its own DB session + runs buy/promote).
    """
    return _default_tick_runner


def get_factory_db() -> Iterator[Session]:
    """Yield a sync DB session (unit-of-work) for the factory store reads.

    Mirrors ``pool_admin.get_pool_admin_db``: the store operations are sync; the
    session commits on clean exit / rolls back on error (via ``get_session``).
    Tests override this dependency to point at the shared test schema.
    """
    with get_session() as session:
        yield session


def _build_redis() -> Redis:
    """Build a short-lived Redis client from settings (mirrors pool_admin pattern).

    Used only by the tick-triggering routes; the client is closed after the route
    returns. Bounded by readiness-check timeouts so a stalled Redis cannot hang.
    """
    settings = get_settings()
    return Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=settings.readiness_check_timeout_seconds,
        socket_timeout=settings.readiness_check_timeout_seconds,
        decode_responses=False,  # run_factory_tick uses bytes redis client
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_factory_account_out(
    record: factory_account_store.FactoryAccountRecord,
) -> FactoryAccountOut:
    """Map a ``FactoryAccountRecord`` to the public ``FactoryAccountOut`` DTO.

    Explicitly omits ``session_string`` and ``proxy`` (both secrets — they exist on
    the record but MUST NOT appear in any API response or log).
    """
    return FactoryAccountOut(
        id=record.id,
        state=record.state,
        phone_masked=record.phone_masked,
        provider=record.provider,
        provider_order_id=record.provider_order_id,
        tg_user_id=record.tg_user_id,
        probation_until=record.probation_until.isoformat() if record.probation_until else None,
        cost_usd=str(record.cost_usd),
        last_error=record.last_error,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
    )


def _require_provider(settings: Settings) -> None:
    """Raise 503 if ``account_factory_provider`` is unset/empty.

    Mutating endpoints call this guard before touching the tick runner or store.
    Read endpoints never call this (they surface ``enabled=False`` instead).
    """
    if not settings.account_factory_provider:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_FACTORY_NOT_CONFIGURED_MESSAGE,
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/accounts",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=FactoryTriggerOut,
    summary="Trigger a factory provisioning tick (superuser only)",
)
async def trigger_factory_tick(
    _user: Annotated[User, Depends(current_superuser)],
    settings: Annotated[Settings, Depends(get_settings)],
    tick_runner: Annotated[_TickRunner, Depends(get_factory_tick_runner)],
) -> FactoryTriggerOut:
    """Enqueue / invoke a synchronous factory tick, then return 202 + summary.

    Provider gate: if ``account_factory_provider`` is unset/empty → 503 with a
    non-secret message (no stack leak). With a provider set the tick runs
    in-process via ``run_in_threadpool`` (the tick is sync + opens its own DB
    session) and returns a summary. The tick is best-effort — an unexpected
    error inside it is logged (exception class only, no secrets) and surfaces as
    500 via the unified envelope.

    The tick runner is injected via ``get_factory_tick_runner()`` so tests can
    substitute a no-op or a fakeredis-backed runner without touching factory core.
    """
    _require_provider(settings)

    redis = _build_redis()
    try:
        await run_in_threadpool(tick_runner, redis, settings)
    finally:
        try:
            redis.close()
        except Exception as exc:
            logger.warning("factory redis close failed: %s", type(exc).__name__)

    return FactoryTriggerOut(status="triggered")


@router.get(
    "/accounts",
    response_model=list[FactoryAccountOut],
    summary="List all factory accounts (superuser only)",
)
async def list_factory_accounts(
    _user: Annotated[User, Depends(current_superuser)],
    db: Annotated[Session, Depends(get_factory_db)],
) -> list[FactoryAccountOut]:
    """Return all factory accounts across every state, ordered by id.

    Iterates ``FACTORY_STATES`` and aggregates results from
    ``factory_account_store.list_by_state``; the combined list is then sorted by
    id for a stable, deterministic ordering. Works even when the provider is
    unset (read-only — no provider gate). ``session_string`` and ``proxy`` are
    NEVER included in the response.
    """
    records: list[factory_account_store.FactoryAccountRecord] = []
    for state in FACTORY_STATES:
        records.extend(await run_in_threadpool(factory_account_store.list_by_state, db, state))

    records.sort(key=lambda r: r.id)
    return [_to_factory_account_out(r) for r in records]


@router.post(
    "/accounts/{account_id}/relogin",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=FactoryTriggerOut,
    summary="Re-trigger provisioning for a factory account (superuser only)",
)
async def relogin_factory_account(
    account_id: int,
    _user: Annotated[User, Depends(current_superuser)],
    db: Annotated[Session, Depends(get_factory_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    tick_runner: Annotated[_TickRunner, Depends(get_factory_tick_runner)],
) -> FactoryTriggerOut:
    """Re-register / relogin a factory account by triggering a provisioning tick.

    Provider gate: 503 when ``account_factory_provider`` is unset/empty (mutating).
    Existence gate: 404 when no factory account with ``account_id`` exists.

    Since targeted single-account re-registration is outside TASK-134's scope (do
    NOT touch factory core), this endpoint triggers the same full factory tick that
    ``POST /factory/accounts`` uses. A future targeted relogin can slot in here once
    factory core exposes a per-account re-register entrypoint. The 202 signals that
    the tick was dispatched; the caller should poll GET /factory/accounts to observe
    any state change.
    """
    # Existence check first (404 beats the provider gate so the caller knows the id
    # is valid independent of configuration state).
    record = await run_in_threadpool(factory_account_store.get, db, account_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_FACTORY_ACCOUNT_NOT_FOUND_MESSAGE,
        )

    _require_provider(settings)

    redis = _build_redis()
    try:
        await run_in_threadpool(tick_runner, redis, settings)
    finally:
        try:
            redis.close()
        except Exception as exc:
            logger.warning("factory redis close (relogin) failed: %s", type(exc).__name__)

    return FactoryTriggerOut(status="triggered")


@router.get(
    "/budget",
    response_model=BudgetOut,
    summary="Factory budget summary (superuser only)",
)
async def get_factory_budget(
    _user: Annotated[User, Depends(current_superuser)],
    db: Annotated[Session, Depends(get_factory_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> BudgetOut:
    """Return budget math: budget / spent / remaining + provider / enabled.

    ``spent_usd`` is ``total_spent_usd`` — the sum of ``cost_usd`` across ALL factory
    rows, INTENTIONALLY including terminal ``failed``/``banned`` accounts: real provider
    money was spent on those buys (sunk cost), so the budget hard-cap counts them. This
    mirrors the tick's own ``can_afford`` check, which sums the same total.

    ``remaining_usd = max(0, budget_usd - spent_usd)`` — never negative even if the
    stored spend exceeds the configured budget (an operator may lower the budget after
    spend has accrued). Money is ``Decimal`` throughout (never float).

    Works even when ``account_factory_provider`` is unset: ``enabled=False`` and
    ``provider=""`` signal the unconfigured state without blocking the read.
    """
    budget_usd: Decimal = settings.account_factory_budget_usd
    spent_usd: Decimal = await run_in_threadpool(factory_account_store.total_spent_usd, db)
    remaining_usd: Decimal = max(Decimal("0"), budget_usd - spent_usd)
    provider = settings.account_factory_provider
    enabled = bool(provider)

    return BudgetOut(
        budget_usd=str(budget_usd),
        spent_usd=str(spent_usd),
        remaining_usd=str(remaining_usd),
        provider=provider,
        enabled=enabled,
    )


__all__ = [
    "BudgetOut",
    "FactoryAccountOut",
    "FactoryTriggerOut",
    "get_factory_db",
    "get_factory_tick_runner",
    "router",
]
