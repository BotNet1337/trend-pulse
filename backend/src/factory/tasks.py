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
from decimal import Decimal
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
from factory.health.base import HealthProbe
from factory.health.factory import get_health_probe
from factory.providers.base import PurchasedNumber, SmsProvider
from factory.providers.factory import get_registrar, get_sms_provider
from factory.proxy.base import ProxyLease, ProxyProvider
from factory.proxy.factory import get_proxy_provider
from factory.registrar.base import RegisteredSession, TelegramRegistrar
from factory.service import assign_proxy, can_afford, is_promotable, needs_topup
from storage import factory_account_store, pool_session_store
from storage.database import get_session
from storage.models.pool_sessions import PoolSession
from storage.redis_client import get_redis_client

if TYPE_CHECKING:
    from redis import Redis

logger = logging.getLogger(__name__)

# Decimal zero for "no proxy cost" (no proxy allocated/assigned) — never float.
_ZERO_USD = Decimal("0")

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


async def _release_lease(proxy_provider: ProxyProvider, lease: ProxyLease) -> None:
    """Best-effort release of a leased proxy port — NEVER raises (mirrors `cancel`, #213).

    Releasing a port must never mask the surrounding registration outcome, so any
    transport blip is swallowed (logged without the secret `uri`). The provider's own
    `release` is best-effort too; this wrapper is belt-and-braces around the await.
    """
    try:
        await proxy_provider.release(lease.lease_id)
    except Exception as exc:
        logger.warning(
            "factory_tick: proxy release failed (best-effort — original outcome kept)",
            extra={"exc_type": type(exc).__name__, "lease_id": lease.lease_id},
        )


async def _provision(
    provider: SmsProvider,
    registrar: TelegramRegistrar,
    *,
    proxy_provider: ProxyProvider | None,
    country: str,
    static_proxy: str | None,
) -> tuple[PurchasedNumber, RegisteredSession, ProxyLease | None]:
    """Buy → (allocate proxy) → poll code → register; finish + return the lease on success.

    When `proxy_provider` is set, a fresh sticky proxy is allocated AFTER the number is
    secured (never hold a proxy without a number) and registration runs over `lease.uri`;
    the lease is returned so the caller persists `proxy`/`proxy_lease_id`. When it is
    `None`, registration runs over `static_proxy` and the returned lease is `None`
    (byte-for-byte the static path). Always closes the provider transport. Typed
    provider/registrar errors propagate to the caller (mapped to the off-ramps); on any
    failure after a lease is held the port is released best-effort (never masks the error).
    """
    try:
        purchased = await provider.buy_number(country=country, service=SMSPVA_DEFAULT_SERVICE)

        lease: ProxyLease | None = None
        if proxy_provider is not None:
            try:
                lease = await proxy_provider.allocate(country=country)
            except Exception:
                # Allocation failed AFTER a number was bought → release the number so we
                # never hold a number without a proxy; propagate the original error.
                await provider.cancel(purchased.order_id)
                raise
        register_proxy = lease.uri if lease is not None else static_proxy

        async def code_cb() -> str:
            return await provider.poll_code(
                purchased.order_id, timeout_seconds=SMS_CODE_POLL_TIMEOUT_SECONDS
            )

        try:
            registered = await registrar.register(
                phone=purchased.phone, code_cb=code_cb, proxy=register_proxy
            )
        except Exception:
            # Registration failed AFTER a number was bought (e.g. Telegram rejects the
            # SMS number — PhoneNumberInvalid/Banned — the COMMON case). RELEASE the
            # number AND (if dynamically leased) the proxy port so neither cost leaks,
            # then propagate the original error. Both releases are best-effort and never
            # raise, so they can't mask the original error.
            await provider.cancel(purchased.order_id)
            if lease is not None:
                await _release_lease(proxy_provider, lease)
            raise
        await provider.finish(purchased.order_id)
        return purchased, registered, lease
    finally:
        await provider.aclose()


def _buy_phase(redis: Redis, session: Session, settings: Settings, now: datetime) -> None:
    """Buy → register → probation when the pool is under target and the budget allows.

    A dynamic `ProxyProvider` (when `get_proxy_provider` returns one) is XOR with the
    static pool: if present, the static pool is IGNORED and a fresh sticky proxy is
    allocated inside `_provision`; otherwise today's static-pool path runs byte-for-byte.
    """
    healthy, target = _read_pool_health(redis, fallback_target=settings.pool_min_healthy)
    if not needs_topup(healthy, target):
        return

    price = settings.account_factory_price_usd
    spent = factory_account_store.total_spent_usd(session)
    if not can_afford(spent, price, settings.account_factory_budget_usd):
        logger.info("factory_tick: budget hard-cap reached — skipping buy this tick")
        return

    proxy_provider = get_proxy_provider(settings)
    if proxy_provider is not None:
        # DYNAMIC path: the proxy is allocated per-buy inside `_provision`; the static
        # pool + `_used_proxies` exhaustion guard do NOT apply.
        static_proxy: str | None = None
    else:
        # STATIC path (byte-for-byte): assign a free proxy from the configured pool.
        pool = account_factory_proxy_pool_list(settings)
        static_proxy = assign_proxy(pool, _used_proxies(session))
        if pool and static_proxy is None:
            logger.info("factory_tick: proxy pool exhausted — skipping buy this tick")
            return

    provider = get_sms_provider(settings)
    registrar = get_registrar(settings)
    try:
        purchased, registered, lease = asyncio.run(
            _provision(
                provider,
                registrar,
                proxy_provider=proxy_provider,
                country=settings.account_factory_country,
                static_proxy=static_proxy,
            )
        )
    except SmsNumberUnavailableError:
        # No number bought → NO row, budget untouched (the simplest correct off-ramp).
        # No proxy was allocated (allocate happens only after a number is in hand).
        logger.warning("factory_tick: no number available — skipping buy (budget untouched)")
        return
    except SmsCodeTimeoutError:
        # Number was bought (budget would be spent) but the code never arrived. Any
        # dynamically-leased proxy was already released inside `_provision` (refunded),
        # so this failed row carries the number price only.
        record = factory_account_store.create_purchased(
            session,
            phone_masked=_MASK_UNKNOWN,
            provider=settings.account_factory_provider,
            provider_order_id=_UNKNOWN_ORDER_ID,
            cost_usd=price,
            proxy=static_proxy,
        )
        factory_account_store.transition(
            session, record.id, FACTORY_STATE_FAILED, last_error="sms code timeout"
        )
        logger.warning("factory_tick: SMS code timeout — account recorded failed")
        return

    # The proxy bound to this account (dynamic lease uri, or the static-pool uri) + its
    # cost. A proxy_price is charged ONLY when a proxy was actually allocated/assigned.
    proxy_uri = lease.uri if lease is not None else static_proxy
    proxy_lease_id = lease.lease_id if lease is not None else None
    proxy_cost = settings.account_factory_proxy_price_usd if proxy_uri is not None else _ZERO_USD
    record = factory_account_store.create_purchased(
        session,
        phone_masked=_mask_phone(purchased.phone),
        provider=settings.account_factory_provider,
        provider_order_id=purchased.order_id,
        cost_usd=price + proxy_cost,
        proxy=proxy_uri,
        proxy_lease_id=proxy_lease_id,
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
        # Release the leased proxy port best-effort (a banned account keeps no proxy).
        if lease is not None and proxy_provider is not None:
            asyncio.run(_release_lease(proxy_provider, lease))
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


def _health_check_ok(
    record: factory_account_store.FactoryAccountRecord, probe: HealthProbe
) -> bool:
    """Honest health gate before promotion: read a public channel over session+proxy.

    Precondition (no network): a row with no `session_string`/`tg_user_id` is not
    probeable → not ok (the registered transition sets both). Otherwise run the injected
    `probe` (fake-deterministic in CI; real Telethon read at the live gate) via
    `asyncio.run` — the factory builds short-lived clients per beat, so a fresh loop is
    correct here. Returns the probe's `.ok`; the probe never raises and never logs the
    session/proxy.
    """
    if record.session_string is None or record.tg_user_id is None:
        return False
    result = asyncio.run(probe.check(session_string=record.session_string, proxy=record.proxy))
    return result.ok


def _release_record_proxy(
    settings: Settings, record: factory_account_store.FactoryAccountRecord
) -> None:
    """Best-effort release of a rejected row's dynamically-leased proxy (140 path).

    A health-rejected account must free its proxy. Only acts when the row carries a
    `proxy_lease_id` AND a dynamic provider is configured (static-pool rows have no
    lease to release). Reconstructs the minimal `ProxyLease` the release helper needs
    (only `lease_id` is used) — never raises (mirrors the registration off-ramps).
    """
    if record.proxy_lease_id is None:
        return
    proxy_provider = get_proxy_provider(settings)
    if proxy_provider is None:
        return
    lease = ProxyLease(
        lease_id=record.proxy_lease_id, uri=record.proxy or "", country=None, expires_at=None
    )
    asyncio.run(_release_lease(proxy_provider, lease))


def _promote_phase(redis: Redis, session: Session, settings: Settings, now: datetime) -> None:
    """Promote each probation row past its gate that passes the health probe.

    Store-write + reload-signal ONLY — the session is never connected here (no
    AuthKeyDuplicated; the probe uses the factory row's own not-yet-live session).
    `upsert_revive_or_add` is idempotent and sets `source='auto'`; the account's proxy
    is carried onto the pool row. A probe-rejected row → `failed` + its proxy released.
    """
    probe = get_health_probe(settings)
    promoted_any = False
    for record in factory_account_store.list_by_state(session, FACTORY_STATE_PROBATION):
        if not is_promotable(record.probation_until, now):
            continue
        if not _health_check_ok(record, probe):
            factory_account_store.transition(
                session, record.id, FACTORY_STATE_FAILED, last_error="health probe failed"
            )
            # A rejected account must free its proxy (best-effort; never crashes the tick).
            _release_record_proxy(settings, record)
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
        _promote_phase(redis, session, settings, now)
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
