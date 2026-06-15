"""collect-tick — the beat ingest task wiring `collector/` into the runtime.

Launch-blocker fix: TASK-005 shipped `TelegramCollector` + the raw buffer and
task-007 shipped the batch that DRAINS that buffer, but no scheduled task ever
called `registry.get(kind).read(...)` → `write_post(...)` — so every batch
drained an empty buffer and prod sat in permanent `warming_up`. This module is
the missing producer tick (mirrors `pipeline.tasks` structurally):

1. gather the DISTINCT `SourceRef`s across ALL active watchlists (a channel
   watched by N tenants is read ONCE — ADR-002 §3, same join as
   `pipeline.batch_processor.user_source_refs` but unscoped),
2. resolve `since` from the last-tick marker in Redis (first tick: a small
   `collect_lookback_seconds` window, never full history; marker clamped to
   the 48h retention window after an outage),
3. per ref: `collector.read([ref], since)` → `collector.buffer.write_post`;
   `AllAccountsFloodWaitError` / `SourceUnavailableError` skip THAT ref with a
   warning and the tick keeps going (the reader already rotates the pool),
4. unconfigured collector (no api creds / empty session pool) → warn-once
   no-op (TASK-044 showcase pattern) — the tick NEVER crashes beat.

Concurrency: a GLOBAL Redis lock (`collector.locks`, `max_instances=1`) keeps
ticks from overlapping — one Telethon session pool must not be hammered by two
ticks at once (FLOOD_WAIT). Cross-tick dedup is NOT re-invented here: the
buffer is drained idempotently and `pipeline.steps.dedup` collapses residual
overlap; `since` just keeps the tick from re-reading the same window forever.

Event loop: Telethon clients are cached in the registry (one `AccountPool` per
worker process) and bind to the loop they first connect on. `asyncio.run()`
would close that loop after the first tick and every later tick would fail with
"Event loop is closed" — so the task drives a PERSISTENT per-process loop via
`run_until_complete`, keeping pool clients and FLOOD_WAIT cooldown state alive
across ticks.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

from celery.exceptions import SoftTimeLimitExceeded
from celery.signals import worker_process_shutdown
from sqlalchemy import select
from sqlalchemy.orm import Session

from celery_app import celery_app
from collector import registry
from collector.base import SourceCollector, SourceKind, SourceRef
from collector.buffer import write_post
from collector.constants import (
    COLLECT_LAST_TICK_KEY,
    COLLECT_TICK_HARD_LIMIT_GRACE_SECONDS,
    COLLECT_TICK_TASK,
    RAW_POST_TTL_SECONDS,
)
from collector.errors import (
    AllAccountsFloodWaitError,
    PoolConfigError,
    PoolExhaustedError,
    SourceUnavailableError,
)
from collector.locks import collect_tick_lock
from config import get_settings
from storage.database import get_session
from storage.models import Channel, Watchlist
from storage.redis_client import get_redis_client

if TYPE_CHECKING:
    from redis import Redis

logger = logging.getLogger(__name__)

# Storage `Channel.source_kind` and collector `SourceKind` are distinct StrEnums
# (different layers); map by value — same seam as `pipeline.batch_processor`.
_KIND_BY_VALUE: dict[str, SourceKind] = {k.value: k for k in SourceKind}

# Kinds already warned about (unconfigured/unregistered collector) — warn-once
# per worker process so a creds-less deploy logs one line, not one per minute
# (same pattern as the showcase autopost creds guard, TASK-044).
_WARNED_UNCONFIGURED_KINDS: set[SourceKind] = set()

# Persistent per-process event loop (see module docstring: registry-cached
# Telethon clients bind to one loop; `asyncio.run` would close it every tick).
_loop: asyncio.AbstractEventLoop | None = None


def _ensure_event_loop() -> asyncio.AbstractEventLoop:
    """Return the worker-process event loop, creating + installing it once.

    `asyncio.set_event_loop` is called so a lazily built Telethon client (which
    resolves `get_event_loop()` at construction) binds to THIS loop — the same
    loop every subsequent tick runs on.
    """
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


@worker_process_shutdown.connect
def _close_collectors_on_shutdown(**_kwargs: object) -> None:
    """Gracefully disconnect cached collectors when a prefork child exits (TASK-106).

    A child exits on `worker_max_tasks_per_child` recycle (TASK-099) or worker stop.
    Without a clean MTProto disconnect, the NEXT child reconnecting the SAME Telegram
    session can trigger `AuthKeyDuplicatedError` (the session looks used from "two
    places") — which permanently kills the session on a small pool. Disconnecting here
    (audit finding-5) reduces that on graceful exits. Best-effort: a SIGKILL (hard time
    limit) skips this, and any aclose error is logged, never raised out of shutdown.
    """
    if _loop is None or _loop.is_closed():
        return
    for collector in registry.cached_collectors():
        try:
            _loop.run_until_complete(collector.aclose())
        except Exception:
            logger.warning(
                "collector aclose failed on worker shutdown",
                extra={"kind": collector.kind.value},
            )
    try:
        _loop.close()
    except Exception:
        logger.warning("event loop close failed on worker shutdown")


def watched_source_refs(session: Session) -> list[SourceRef]:
    """Return the DISTINCT `SourceRef`s watched by ANY active watchlist.

    Read-only join `watchlists → channels` with no user filter — the union of
    every tenant's sources, deduplicated so a channel on many watchlists is
    read once per tick (ADR-002 §3; the per-user batch re-filters later).
    """
    stmt = (
        select(Channel.source_kind, Channel.handle)
        .join(Watchlist, Watchlist.channel_id == Channel.id)
        .distinct()
    )
    rows = session.execute(stmt).all()
    return [
        SourceRef(kind=_KIND_BY_VALUE[source_kind.value], handle=handle)
        for source_kind, handle in rows
    ]


def _resolve_since(redis: "Redis", now: datetime) -> datetime:
    """Resolve the tick's `since` lower bound from the last-tick marker.

    No marker (first tick) or a corrupt/naive one → `now - collect_lookback`
    (a small recent window, never full history). A stale marker (long outage)
    is clamped to the 48h retention window — raw content older than that may
    not be ingested anyway (compliance, ADR-002 §4). A marker from the future
    (clock skew) is clamped back to `now`.
    """
    fallback = now - timedelta(seconds=get_settings().collect_lookback_seconds)
    raw = cast("bytes | str | None", redis.get(COLLECT_LAST_TICK_KEY))
    if raw is None:
        return fallback
    text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    try:
        stored = datetime.fromisoformat(text)
    except ValueError:
        logger.warning("collect_tick: corrupt last-tick marker — using lookback window")
        return fallback
    if stored.tzinfo is None:
        logger.warning("collect_tick: naive last-tick marker — using lookback window")
        return fallback
    floor = now - timedelta(seconds=RAW_POST_TTL_SECONDS)
    return min(max(stored, floor), now)


async def _collect_refs(
    collector: SourceCollector,
    refs: list[SourceRef],
    since: datetime,
    redis: "Redis",
) -> int:
    """Read each ref and buffer its posts; a failing ref never kills the rest.

    `read()` is called per ref (not with the whole list) because an exception
    inside the async generator would abort every remaining ref — per-ref calls
    give the skip-and-continue semantics the tick needs. Cross-ref handle dedup
    already happened in the DISTINCT SQL; the reader normalizes per call.
    """
    written = 0
    for ref in refs:
        try:
            async for post in collector.read([ref], since):
                write_post(redis, post)
                written += 1
        except (
            AllAccountsFloodWaitError,
            PoolExhaustedError,
            SourceUnavailableError,
        ) as exc:
            # The reader already rotated/backed off/quarantined; skip this ref, keep
            # the rest. PoolExhaustedError (all sessions dead, TASK-087) skips here
            # too — the per-account dead-session alert already told ops to re-mint.
            logger.warning(
                "collect_tick: source skipped kind=%s handle=%s (%s)",
                ref.kind.value,
                ref.handle,
                type(exc).__name__,
            )
    return written


def _warn_unconfigured_once(kind: SourceKind, reason: str) -> None:
    """Warn ONCE per process per kind that its collector cannot run."""
    if kind in _WARNED_UNCONFIGURED_KINDS:
        return
    _WARNED_UNCONFIGURED_KINDS.add(kind)
    logger.warning(
        "collect_tick: collector unconfigured for kind=%s — ingest is a no-op (%s)",
        kind.value,
        reason,
    )


def collect_watched_sources(redis: "Redis", *, now: datetime | None = None) -> int:
    """One collect pass: distinct refs → `read(since)` → buffer. Returns posts written.

    The last-tick marker advances to this tick's START time only when at least
    one collector actually ran — an unconfigured-pool no-op must not silently
    open a data gap for when credentials arrive. Posts published mid-read are
    still covered next tick because the marker is the start, not the end.
    """
    if now is None:
        now = datetime.now(UTC)
    since = _resolve_since(redis, now)

    with get_session() as session:
        refs = watched_source_refs(session)
    if not refs:
        logger.info("collect_tick no-op (no watched sources)")
        return 0

    refs_by_kind: dict[SourceKind, list[SourceRef]] = {}
    for ref in refs:
        refs_by_kind.setdefault(ref.kind, []).append(ref)

    written = 0
    attempted_any = False
    for kind, kind_refs in refs_by_kind.items():
        if not registry.is_registered(kind):
            # Declared-but-unimplemented kinds (e.g. TWITTER, ADR-001 marker).
            _warn_unconfigured_once(kind, "no collector registered")
            continue
        # Install the persistent loop BEFORE the lazy registry build so Telethon
        # clients constructed inside the factory bind to it (module docstring).
        loop = _ensure_event_loop()
        try:
            collector = registry.get(kind)
        except PoolConfigError as exc:
            # Missing api creds / empty session pool → warn-once no-op (the tick
            # must not crash beat; configure TELEGRAM_API_ID/API_HASH/POOL_SESSIONS).
            _warn_unconfigured_once(kind, str(exc))
            continue
        attempted_any = True
        written += loop.run_until_complete(_collect_refs(collector, kind_refs, since, redis))

    if attempted_any:
        # TTL (TASK-101): the one ingest key that previously never expired. Set it to
        # the retention window — `_resolve_since` already falls back to the recent
        # window if the marker is absent, so an expired marker after a long outage is
        # safe (and the value is re-stamped every tick during normal operation).
        redis.set(COLLECT_LAST_TICK_KEY, now.isoformat(), ex=RAW_POST_TTL_SECONDS)
    logger.info(
        "collect_tick collected posts=%d refs=%d since=%s",
        written,
        len(refs),
        since.isoformat(),
    )
    return written


# Soft limit = the lock TTL: a tick may use its whole lock window, never more
# (after the TTL another tick could start — two ticks must not share the pool).
# Resolved once at import, same as `celery_app`'s own `get_settings()` wiring.
_TICK_SOFT_TIME_LIMIT_SECONDS = get_settings().collect_lock_ttl_seconds


@celery_app.task(
    name=COLLECT_TICK_TASK,
    soft_time_limit=_TICK_SOFT_TIME_LIMIT_SECONDS,
    time_limit=_TICK_SOFT_TIME_LIMIT_SECONDS + COLLECT_TICK_HARD_LIMIT_GRACE_SECONDS,
)
def collect_tick() -> None:
    """Beat ingest tick: read watched sources into the raw buffer (global lock).

    Held lock (an in-flight tick) → clean no-op, so beat double-fires and slow
    reads can never overlap on the single Telethon pool (`max_instances=1`,
    mirrors `run_user_batch`). Best-effort body: any unexpected error is logged
    and suppressed — beat must never crash (showcase-tick invariant).

    Time limits are the safety net under the FLOOD_WAIT inline cap (reader): a
    read wedged past the lock TTL gets SoftTimeLimitExceeded — a VALID partial
    tick (posts buffered before the cut stay buffered; the lock is released by
    the context manager) — and the hard limit recycles the worker process if
    even that cleanup hangs, so a stuck read can never pin a celery slot.
    """
    redis = get_redis_client()
    with collect_tick_lock(redis) as acquired:
        if not acquired:
            logger.info("collect_tick skipped: locked")
            return
        try:
            collect_watched_sources(redis)
        except SoftTimeLimitExceeded:
            logger.warning(
                "collect_tick soft time limit hit (%ds) — partial tick kept "
                "(already-buffered posts remain valid)",
                _TICK_SOFT_TIME_LIMIT_SECONDS,
            )
        except Exception as exc:
            logger.warning(
                "collect_tick unexpected error — suppressed",
                extra={"exc_type": type(exc).__name__},
            )
