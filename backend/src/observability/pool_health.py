"""TG account pool health metric + ops self-alert (TASK-035).

Two public functions:

- ``emit_pool_health(pool, settings)`` — compute pool aggregates (size, cooling,
  healthy, target, degraded) and emit via ``log_event``. Returns the aggregates
  dict so callers can inspect the state (e.g. to decide whether to call
  ``notify_ops``). NEVER includes session strings or secrets.

- ``notify_ops(reason, text, settings, redis)`` — throttle via Redis SET NX EX,
  then POST a plain-text ops message to the configured Telegram ops bot.  All
  failure modes are best-effort: Redis unavailable → skip send + warn (no spam
  during a network storm); HTTP error → warn; empty token/chat → silent skip.
  NEVER raises — self-observation must not crash the collector (Invariant).

Design:
- Throttle key format: ``ops_alert:{reason}`` — one key per reason so "all_flood"
  and "pool_below_target" throttle independently.
- HTTP: reuses ``httpx.post`` exactly as ``alerts/backends.py::TelegramBotBackend``
  does (same library, same call pattern). No SSRF guard needed — the endpoint is
  the ops-controlled Telegram Bot API base, not a user-supplied URL.
- Token is ``repr=False`` is enforced at source (TelegramTarget in backends.py);
  here we never log the token either — only the non-secret chat_id may appear.

Import note: this module does NOT import ``celery_app`` or ORM models, so it is
safe to import from any context (beat worker, API, pure unit tests) without
circular dependencies.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
from redis.exceptions import RedisError

from collector.constants import POOL_HEALTH_REDIS_KEY, POOL_HEALTH_SNAPSHOT_TTL_SECONDS
from observability.logging import log_event

if TYPE_CHECKING:
    from redis import Redis

    from collector.telegram.account_pool import AccountPool
    from config import Settings

logger = logging.getLogger(__name__)

# Redis throttle key prefix — one key per alert reason.
_THROTTLE_KEY_PREFIX = "ops_alert"

# HTTP status threshold — any code >= this is an error response.
_HTTP_ERROR_FLOOR = 400


def emit_pool_health(
    pool: AccountPool,
    settings: Settings,
    redis: Redis | None = None,
) -> dict[str, object]:
    """Compute and log pool health aggregates; optionally bridge a snapshot to Redis.

    Aggregates emitted (no session strings, no secrets):
    - ``size``     — total accounts in pool
    - ``cooling``  — accounts currently in FLOOD_WAIT cooldown
    - ``healthy``  — accounts available (size - cooling)
    - ``target``   — ``pool_min_healthy`` operational target
    - ``degraded`` — True when healthy < target

    When ``redis`` is given (TASK-115), the FULL snapshot (the aggregates above plus an
    ``accounts`` list of per-account statuses and an ``as_of`` UTC-ISO timestamp) is
    written as JSON to ``POOL_HEALTH_REDIS_KEY`` with ``POOL_HEALTH_SNAPSHOT_TTL_SECONDS``
    TTL, so the API process (TASK-116) can read the freshest state cross-process and
    compute staleness. The write is BEST-EFFORT: any failure logs and is swallowed so
    self-observation never breaks the collect-tick (Invariant). The snapshot carries NO
    secrets — per-account identity is the stable pool INDEX only.

    Args:
        pool:     The ``AccountPool`` instance to inspect.
        settings: Application settings (provides ``pool_min_healthy``).
        redis:    Optional Redis client; when given, the snapshot is published.

    Returns:
        Dict of the logged aggregates (return shape unchanged for existing callers).
    """
    size: int = pool.size
    cooling: int = pool.cooling_count
    quarantined: int = pool.quarantined_count
    # Quarantined (dead) accounts are neither cooling nor healthy — subtract both so
    # `healthy` reflects accounts that can actually serve a read (TASK-087).
    healthy: int = size - cooling - quarantined
    target: int = settings.pool_min_healthy
    degraded: bool = healthy < target

    log_event(
        "pool_health",
        size=size,
        cooling=cooling,
        quarantined=quarantined,
        healthy=healthy,
        target=target,
        degraded=degraded,
    )
    aggregates: dict[str, object] = {
        "size": size,
        "cooling": cooling,
        "quarantined": quarantined,
        "healthy": healthy,
        "target": target,
        "degraded": degraded,
    }
    if redis is not None:
        _publish_snapshot(pool, aggregates, redis)
    return aggregates


def _publish_snapshot(
    pool: AccountPool,
    aggregates: dict[str, object],
    redis: Redis,
) -> None:
    """Write the full pool-health snapshot as JSON to Redis (TASK-115; best-effort).

    The snapshot is ``aggregates`` plus an ``accounts`` list (per-account statuses as
    plain dicts) and an ``as_of`` UTC-ISO timestamp for staleness computation. A
    serialization or Redis failure is logged and swallowed — the collect-tick must
    never break on self-observation (Invariant). No secrets: index-only identity.
    """
    try:
        snapshot: dict[str, object] = {
            **aggregates,
            "as_of": datetime.now(UTC).isoformat(),
            "accounts": [asdict(status) for status in pool.account_statuses()],
        }
        redis.set(
            POOL_HEALTH_REDIS_KEY,
            json.dumps(snapshot),
            ex=POOL_HEALTH_SNAPSHOT_TTL_SECONDS,
        )
    except (RedisError, TypeError, ValueError) as exc:
        logger.warning(
            "pool health snapshot Redis write failed — skipping",
            extra={"exc_type": type(exc).__name__},
        )


def notify_ops(
    reason: str,
    text: str,
    settings: Settings,
    redis: Redis,
) -> None:
    """Send a self-alert to the ops Telegram chat — best-effort, never raises.

    Throttle: at most one message per ``reason`` per ``ops_alert_throttle_seconds``
    window (Redis SET NX EX).  If Redis is unavailable the send is SKIPPED (not
    spammed) and a warning is logged — fail-open to LOG ONLY during network storms.

    Empty ``ops_telegram_bot_token`` or ``ops_telegram_chat_id`` → silent no-op
    (metric-only mode, no send, no log noise for dev environments).

    HTTP delivery failures (network errors or non-2xx) are swallowed as warnings —
    self-observation must never crash the collector (Invariant).

    Args:
        reason:   Short slug identifying the alert kind (e.g. "all_flood").
                  Used as the Redis throttle key discriminator.
        text:     Plain-text message to send to the ops chat. Must NOT contain
                  session strings, tokens, or raw post content (aggregates only).
        settings: Application settings (provides token, chat_id, throttle window).
        redis:    Redis client for the throttle key (caller provides/manages it).
    """
    token: str = settings.ops_telegram_bot_token
    chat_id: str = settings.ops_telegram_chat_id

    # Silent no-op when ops bot is not configured (dev / metric-only mode).
    if not token or not chat_id:
        return

    # Throttle via Redis SET NX EX (one message per reason per throttle window).
    throttle_key = f"{_THROTTLE_KEY_PREFIX}:{reason}"
    try:
        acquired = redis.set(
            throttle_key,
            "1",
            nx=True,
            ex=settings.ops_alert_throttle_seconds,
        )
    except RedisError as exc:
        # Redis unavailable → fail-open: skip the send (no spam), warn and return.
        logger.warning(
            "ops_alert throttle Redis error — skipping send",
            extra={"reason": reason, "exc_type": type(exc).__name__},
        )
        return

    if not acquired:
        # Key already exists → throttled; log at WARNING so it's visible in ops logs.
        logger.warning(
            "ops_alert throttled",
            extra={"reason": reason, "throttle_seconds": settings.ops_alert_throttle_seconds},
        )
        return

    # Send via Telegram Bot API (same HTTP call as TelegramBotBackend — no SSRF
    # guard needed; the base URL is our own Telegram API base, not user-supplied).
    base_url = settings.telegram_api_base_url.rstrip("/")
    url = f"{base_url}/bot{token}/sendMessage"
    body = {"chat_id": chat_id, "text": text}
    try:
        response = httpx.post(url, json=body, timeout=settings.alert_http_timeout_seconds)
        if response.status_code >= _HTTP_ERROR_FLOOR:
            logger.warning(
                "ops_alert HTTP error",
                extra={"reason": reason, "status_code": response.status_code},
            )
    except httpx.HTTPError as exc:
        logger.warning(
            "ops_alert delivery failed",
            extra={"reason": reason, "exc_type": type(exc).__name__},
        )
    except Exception as exc:
        # Broad catch is intentional safety net: notify_ops must NEVER raise
        # regardless of unexpected errors (e.g. encoding errors, unexpected
        # httpx internals).  Log only the exception type — never url/value
        # which could contain the bot token.
        logger.warning(
            "ops_alert unexpected error — suppressed",
            extra={"reason": reason, "exc_type": type(exc).__name__},
        )
