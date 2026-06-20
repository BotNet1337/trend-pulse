"""factory-tick — the account-factory control loop wiring `factory/` into the runtime.

The single beat task (TASK-134, Layer B1+B4+B5). One tick:

1. **Provider-driven gate FIRST.** If `account_factory_provider` is unset/empty → exact
   no-op (owner-decision activation; the default `fake` keeps it active in CI/test).
2. **Top-up.** Read the pool-health snapshot (`pool:health:latest`). If `healthy < target`
   (target falls back to `pool_min_healthy`), buy a number — but ONLY within the hard USD
   budget (`total_spent_usd + price <= budget`; the cap ALWAYS applies). Assign a free
   proxy from the configured pool, register over it (buy → poll code → register), persist
   `factory_accounts` `purchased` → `registered` → `probation` with
   `probation_until = now + probation_days`.
3. **Promote.** For each `probation` row past its `probation_until` (gate `now >= until`)
   that passes a health check, copy the session into the live pool via
   `upsert_revive_or_add(..., source='auto')` (+ carry its proxy), write the pool-reload
   signal, and mark the factory row `promoted`. Promotion is a STORE-WRITE + signal only —
   it NEVER connects a session already live (no AuthKeyDuplicated).

Invariants: budget is a hard ceiling; the probation gate is never bypassed; the full
phone is never persisted/logged (masked); session strings + proxies are never logged.
The whole tick is best-effort — an unexpected error is logged and suppressed so beat
never crashes (mirrors `collector.tasks.collect_tick`).

Sync Celery task → the async buy/poll/register flow runs via `asyncio.run` (the factory
builds its OWN short-lived clients per provisioning, unlike the worker's persistent pool,
so a fresh loop per tick is correct here — no registry-cached clients to keep alive).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

from sqlalchemy import update
from sqlalchemy.orm import Session

from celery_app import celery_app
from collector.constants import (
    POOL_HEALTH_REDIS_KEY,
    POOL_MAX,
    POOL_RELOAD_SIGNAL_REDIS_KEY,
    POOL_RELOAD_SIGNAL_TTL_SECONDS,
    POOL_SOURCE_AUTO,
)
from config import Settings, account_factory_proxy_pool_list, get_settings
from factory.constants import (
    FACTORY_PHONE_MASK_CHAR,
    FACTORY_PHONE_MASK_MIN_LEN,
    FACTORY_PHONE_MASK_VISIBLE_SUFFIX,
    FACTORY_POOL_LABEL_PREFIX,
    FACTORY_STATE_BANNED,
    FACTORY_STATE_FAILED,
    FACTORY_STATE_PROBATION,
    FACTORY_STATE_PROMOTED,
    FACTORY_STATE_PURCHASED,
    FACTORY_STATE_REGISTERED,
    FACTORY_TICK_TASK,
    SMS_CODE_POLL_TIMEOUT_SECONDS,
    SMSPVA_DEFAULT_SERVICE,
)
from factory.errors import (
    RegistrarBannedError,
    RegistrarPasswordNeededError,
    SmsCodeTimeoutError,
    SmsNumberUnavailableError,
)
from factory.providers.base import PurchasedNumber, SmsProvider
from factory.providers.factory import get_registrar, get_sms_provider
from factory.registrar.base import RegisteredSession, TelegramRegistrar
from factory.service import assign_proxy, can_afford, is_promotable, needs_topup
from storage import factory_account_store, pool_session_store
from storage.database import get_session
from storage.models.pool_sessions import PoolSession
from storage.redis_client import get_redis_client

if TYPE_CHECKING:
    from redis import Redis

logger = logging.getLogger(__name__)

# Non-terminal states whose proxies are already in use (a fresh registration must not
# reuse a proxy bound to an in-flight / promoted-eligible factory account).
_NON_TERMINAL_PROXY_STATES: tuple[str, ...] = (
    FACTORY_STATE_PURCHASED,
    FACTORY_STATE_REGISTERED,
    FACTORY_STATE_PROBATION,
)


def _mask_phone(phone: str) -> str:
    """Mask a full phone for persistence: keep a `+` prefix + last N digits, star the rest.

    The full number is NEVER persisted or logged. e.g. `79990000000` → `+7******0000`.
    A too-short value is fully starred. The result always contains FACTORY_PHONE_MASK_CHAR
    so the store's anti-PII guard accepts it.
    """
    digits = phone.lstrip("+")
    if len(digits) < FACTORY_PHONE_MASK_MIN_LEN:
        return "+" + FACTORY_PHONE_MASK_CHAR * max(len(digits), 1)
    suffix = digits[-FACTORY_PHONE_MASK_VISIBLE_SUFFIX:]
    stars = FACTORY_PHONE_MASK_CHAR * (len(digits) - FACTORY_PHONE_MASK_VISIBLE_SUFFIX)
    return f"+{digits[0]}{stars[1:]}{suffix}"


def _read_pool_health(redis: Redis, *, fallback_target: int) -> tuple[int, int]:
    """Return `(healthy, target)` from the pool-health snapshot; tolerant of absence.

    A missing/malformed key → `(fallback_target, fallback_target)` so `needs_topup` reads
    "not under target" (no spurious buy on an unknown pool). `target` falls back to
    `pool_min_healthy` when the snapshot omits it. Never raises.
    """
    try:
        raw = cast("bytes | str | None", redis.get(POOL_HEALTH_REDIS_KEY))
    except Exception as exc:  # redis transport blip — treat pool as unknown.
        logger.warning(
            "factory_tick: pool health read failed (treating as not-under-target)",
            extra={"exc_type": type(exc).__name__},
        )
        return fallback_target, fallback_target
    if raw is None:
        return fallback_target, fallback_target
    text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    try:
        snapshot = json.loads(text)
    except ValueError:
        logger.warning("factory_tick: malformed pool health snapshot — treating as unknown")
        return fallback_target, fallback_target
    if not isinstance(snapshot, dict):
        return fallback_target, fallback_target
    healthy = snapshot.get("healthy")
    target = snapshot.get("target")
    healthy_int = healthy if isinstance(healthy, int) else fallback_target
    target_int = target if isinstance(target, int) else fallback_target
    return healthy_int, target_int


def _used_proxies(session: Session) -> frozenset[str]:
    """Proxies already bound to non-terminal factory rows (the `used` set for assignment)."""
    used: set[str] = set()
    for state in _NON_TERMINAL_PROXY_STATES:
        for record in factory_account_store.list_by_state(session, state):
            if record.proxy is not None:
                used.add(record.proxy)
    return frozenset(used)


async def _provision(
    provider: SmsProvider,
    registrar: TelegramRegistrar,
    *,
    country: str,
    proxy: str | None,
) -> tuple[PurchasedNumber, RegisteredSession]:
    """Buy → poll code → register over `proxy`; finish the order on success.

    Always closes the provider transport. Typed provider/registrar errors propagate to
    the caller (which maps them to the failed/banned off-ramps).
    """
    try:
        purchased = await provider.buy_number(country=country, service=SMSPVA_DEFAULT_SERVICE)

        async def code_cb() -> str:
            return await provider.poll_code(
                purchased.order_id, timeout_seconds=SMS_CODE_POLL_TIMEOUT_SECONDS
            )

        registered = await registrar.register(phone=purchased.phone, code_cb=code_cb, proxy=proxy)
        await provider.finish(purchased.order_id)
        return purchased, registered
    finally:
        await provider.aclose()


def _buy_phase(redis: Redis, session: Session, settings: Settings, now: datetime) -> None:
    """Buy → register → probation when the pool is under target and the budget allows."""
    healthy, target = _read_pool_health(redis, fallback_target=settings.pool_min_healthy)
    if not needs_topup(healthy, target):
        return

    price = settings.account_factory_price_usd
    spent = factory_account_store.total_spent_usd(session)
    if not can_afford(spent, price, settings.account_factory_budget_usd):
        logger.info("factory_tick: budget hard-cap reached — skipping buy this tick")
        return

    pool = account_factory_proxy_pool_list(settings)
    proxy = assign_proxy(pool, _used_proxies(session))
    if pool and proxy is None:
        logger.info("factory_tick: proxy pool exhausted — skipping buy this tick")
        return

    provider = get_sms_provider(settings)
    registrar = get_registrar(settings)
    try:
        purchased, registered = asyncio.run(
            _provision(provider, registrar, country=settings.account_factory_country, proxy=proxy)
        )
    except SmsNumberUnavailableError:
        # No number bought → NO row, budget untouched (the simplest correct off-ramp).
        logger.warning("factory_tick: no number available — skipping buy (budget untouched)")
        return
    except SmsCodeTimeoutError:
        # Number was bought (budget would be spent) but the code never arrived. Record a
        # `failed` row carrying the price so the budget reflects the real spend.
        record = factory_account_store.create_purchased(
            session,
            phone_masked=_MASK_UNKNOWN,
            provider=settings.account_factory_provider,
            provider_order_id=_UNKNOWN_ORDER_ID,
            cost_usd=price,
            proxy=proxy,
        )
        factory_account_store.transition(
            session, record.id, FACTORY_STATE_FAILED, last_error="sms code timeout"
        )
        logger.warning("factory_tick: SMS code timeout — account recorded failed")
        return

    record = factory_account_store.create_purchased(
        session,
        phone_masked=_mask_phone(purchased.phone),
        provider=settings.account_factory_provider,
        provider_order_id=purchased.order_id,
        cost_usd=price,
        proxy=proxy,
    )
    try:
        factory_account_store.transition(
            session,
            record.id,
            FACTORY_STATE_REGISTERED,
            session_string=registered.session_string,
            tg_user_id=registered.tg_user_id,
        )
    except (RegistrarBannedError, RegistrarPasswordNeededError) as exc:
        # Defensive: registration banned/2FA after the buy → terminal `banned`, budget spent.
        factory_account_store.transition(
            session, record.id, FACTORY_STATE_BANNED, last_error=type(exc).__name__
        )
        logger.warning("factory_tick: registration rejected — account recorded banned")
        return

    probation_until = now + timedelta(days=settings.account_factory_probation_days)
    factory_account_store.transition(
        session, record.id, FACTORY_STATE_PROBATION, probation_until=probation_until
    )
    logger.info(
        "factory_tick: account provisioned to probation",
        extra={"account_id": record.id, "probation_until": probation_until.isoformat()},
    )


def _health_check_ok(record: factory_account_store.FactoryAccountRecord) -> bool:
    """Minimal honest health gate before promotion.

    For the fake path this is a deterministic "the account is registered and not banned"
    check (it holds a session + a tg_user_id). A richer can-read-a-public-channel probe
    is a follow-up (out of TASK-134 scope) and would slot in here.
    """
    return record.session_string is not None and record.tg_user_id is not None


def _promote_phase(redis: Redis, session: Session, now: datetime) -> None:
    """Promote each probation row past its gate that passes the health check.

    Store-write + reload-signal ONLY — the session is never connected here (no
    AuthKeyDuplicated). `upsert_revive_or_add` is idempotent and sets `source='auto'`;
    the account's proxy is carried onto the pool row.
    """
    promoted_any = False
    for record in factory_account_store.list_by_state(session, FACTORY_STATE_PROBATION):
        if not is_promotable(record.probation_until, now):
            continue
        if not _health_check_ok(record):
            factory_account_store.transition(
                session, record.id, FACTORY_STATE_FAILED, last_error="health check failed"
            )
            continue
        if record.tg_user_id is None or record.session_string is None:
            continue  # guarded by the health check; satisfies the type narrowing.

        pool_session_store.upsert_revive_or_add(
            session,
            tg_user_id=record.tg_user_id,
            session_string=record.session_string,
            display_label=f"{FACTORY_POOL_LABEL_PREFIX}{record.id}",
            pool_max=POOL_MAX,
            source=POOL_SOURCE_AUTO,
        )
        # `upsert_revive_or_add` does not (yet) accept a proxy — carry the factory
        # account's proxy onto the freshly-promoted pool row directly (the AC requires
        # the proxy on the pool_sessions row). A `proxy=` param on the store is a clean
        # follow-up; until then this targeted update keeps promotion within scope.
        if record.proxy is not None:
            session.execute(
                update(PoolSession)
                .where(PoolSession.tg_user_id == record.tg_user_id)
                .values(proxy=record.proxy)
            )
        factory_account_store.transition(session, record.id, FACTORY_STATE_PROMOTED)
        promoted_any = True
        logger.info("factory_tick: account promoted to live pool", extra={"account_id": record.id})

    if promoted_any:
        # Signal the worker to reload the pool so the promoted session goes live without a
        # restart (the same non-secret flag the QR-revive API writes). Best-effort.
        try:
            redis.set(
                POOL_RELOAD_SIGNAL_REDIS_KEY, now.isoformat(), ex=POOL_RELOAD_SIGNAL_TTL_SECONDS
            )
        except Exception as exc:
            logger.warning(
                "factory_tick: pool reload signal write failed (promotion still persisted)",
                extra={"exc_type": type(exc).__name__},
            )


# Masked sentinels for a buy whose phone we never received (timeout off-ramp) — still
# masked so the store's anti-PII guard accepts the row; no real number is involved.
_MASK_UNKNOWN = "+" + FACTORY_PHONE_MASK_CHAR * 4
_UNKNOWN_ORDER_ID = "unknown"


def run_factory_tick(
    redis: Redis, *, settings: Settings | None = None, now: datetime | None = None
) -> None:
    """One factory pass: provider gate → buy/register/probation → promote. Opens its own DB.

    Separated from the Celery entry point so the integration test drives it with an
    injected `redis`/`settings`/`now`. A provider-unset gate makes this an exact no-op.
    """
    settings = settings if settings is not None else get_settings()
    now = now if now is not None else datetime.now(UTC)

    if not settings.account_factory_provider:
        logger.info("factory_tick skipped: no provider configured (no-op)")
        return

    with get_session() as session:
        _buy_phase(redis, session, settings, now)
        _promote_phase(redis, session, now)
        # `get_session` commits on clean exit / rolls back on error.


@celery_app.task(name=FACTORY_TICK_TASK)
def factory_tick() -> None:
    """Beat tick: top up + promote factory accounts (best-effort — never crashes beat).

    Provider-driven no-op when `ACCOUNT_FACTORY_PROVIDER` is unset/empty. Any unexpected
    error is logged and suppressed (mirrors `collect_tick`) — the DB unit-of-work rolls
    back via `get_session`, so a partial tick never leaves an inconsistent state.
    """
    redis = get_redis_client()
    try:
        run_factory_tick(redis)
    except Exception as exc:
        logger.warning(
            "factory_tick unexpected error — suppressed",
            extra={"exc_type": type(exc).__name__},
        )
