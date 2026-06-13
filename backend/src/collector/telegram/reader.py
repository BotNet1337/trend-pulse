"""`TelegramCollector` — the Telegram `SourceCollector` (AC2/AC3/AC4/AC5).

Telegram specifics (Telethon errors, entity resolution, iteration) are confined to
this module plus `account_pool`/`mapper`/`dedup`. `read` builds the UNION of unique
refs (cross-tenant dedup), reads each channel once, maps each message via the pure
mapper, and on FLOOD_WAIT applies backoff + account rotation without crashing.

Pool health (TASK-035): `emit_pool_health` + `notify_ops` are called best-effort at
key degradation points — they never propagate exceptions (Invariant: self-observation
must not crash collection).
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING

from collector.base import RawPost, SourceKind, SourceRef
from collector.constants import (
    FLOOD_WAIT_INLINE_CAP_SECONDS,
    INTER_REQUEST_SLEEP_SECONDS,
    MAX_MESSAGES_PER_TICK,
)
from collector.errors import AllAccountsFloodWaitError, SourceUnavailableError
from collector.telegram.account_pool import AccountPool
from collector.telegram.client import TelegramClientProtocol
from collector.telegram.dedup import normalize_handle, unique_refs
from collector.telegram.mapper import map_entity

if TYPE_CHECKING:
    from redis import Redis

    from config import Settings

logger = logging.getLogger(__name__)

# Telethon error types are resolved lazily (the SDK is imported only when present)
# so this module imports cleanly in pure-unit contexts. We match on a `seconds`
# attribute structurally rather than importing FloodWaitError at module load.
_AsyncSleep = Callable[[float], Awaitable[None]]


def _flood_wait_seconds(error: BaseException) -> float | None:
    """Return the FLOOD_WAIT retry hint if `error` looks like a FloodWaitError."""
    seconds = getattr(error, "seconds", None)
    if isinstance(seconds, int | float):
        return float(seconds)
    return None


async def _ensure_connected(client: TelegramClientProtocol) -> None:
    """Connect `client` only if it is not connected yet.

    Re-calling `connect()` on a live Telethon client logs "User is already
    connected!" and was part of the prod hang signature (pool=1 "rotation"
    re-acquired the same connected account every retry).
    """
    if not client.is_connected():
        await client.connect()


class TelegramCollector:
    """Telegram implementation of the `SourceCollector` port."""

    kind: SourceKind = SourceKind.TELEGRAM

    def __init__(
        self,
        pool: AccountPool,
        *,
        sleep: _AsyncSleep | None = None,
        settings: "Settings | None" = None,
        redis: "Redis | None" = None,
    ) -> None:
        self._pool = pool
        # Injectable async sleep keeps unit tests instant (no real backoff waits).
        self._sleep: _AsyncSleep = sleep if sleep is not None else asyncio.sleep
        # Optional: settings + redis for pool health self-observation (TASK-035).
        # When None, health calls are skipped — unit tests and backwards-compat.
        self._settings = settings
        self._redis = redis

    def _emit_health_best_effort(
        self,
        *,
        notify_reason: str | None = None,
        notify_text: str | None = None,
    ) -> None:
        """Emit pool health metric + optionally send an ops self-alert (best-effort).

        NEVER raises — swallows all exceptions with a warn log so self-observation
        cannot crash the collector (Invariant).  When settings/redis are None (unit
        tests, backwards-compat callers) the call is a silent no-op.
        """
        if self._settings is None or self._redis is None:
            return
        try:
            from observability.pool_health import emit_pool_health, notify_ops

            result = emit_pool_health(self._pool, self._settings)
            if notify_reason is not None and notify_text is not None:
                notify_ops(
                    reason=notify_reason,
                    text=notify_text,
                    settings=self._settings,
                    redis=self._redis,
                )
            elif result["degraded"] and notify_reason is None:
                # Periodic tick: degraded → self-alert without an explicit reason.
                notify_ops(
                    reason="pool_below_target",
                    text=(
                        f"TG pool degraded: {result['healthy']} healthy, "
                        f"target {result['target']}, cooling {result['cooling']}"
                    ),
                    settings=self._settings,
                    redis=self._redis,
                )
        except Exception as exc:
            logger.warning(
                "pool health observation failed",
                extra={"exc_type": type(exc).__name__},
            )

    async def aclose(self) -> None:
        """Disconnect all pool clients — call on worker shutdown so MTProto
        connections aren't leaked across the worker's lifetime."""
        await self._pool.aclose()

    async def __aenter__(self) -> "TelegramCollector":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def validate_ref(self, ref: SourceRef) -> bool:
        """True iff `ref` is a readable public channel; never raises outward (AC2)."""
        if ref.kind is not SourceKind.TELEGRAM:
            return False
        handle = normalize_handle(ref.handle, ref.kind)
        try:
            client = self._pool.acquire()
            await _ensure_connected(client)
            await client.get_entity(handle)
        except AllAccountsFloodWaitError:
            # Transient pool exhaustion — cannot confirm, treat as not-validated now.
            return False
        except Exception:
            # Private / nonexistent / invalid handle, or network: not a public ref.
            # We intentionally catch broadly here BUT never re-raise (AC2 contract).
            logger.info("validate_ref rejected handle (not a public channel)")
            return False
        return True

    async def read(self, refs: list[SourceRef], since: datetime | None) -> AsyncIterator[RawPost]:
        """Yield `RawPost`s for the unique union of `refs` newer than `since` (AC5).

        Emits a single pool health metric + degraded self-alert once per read()
        invocation — after all channels have been processed (TASK-035: periodic
        svodka, no new Beat schedule — uses existing read loop).
        """
        for ref in unique_refs(refs):
            async for post in self._read_one(ref, since):
                yield post
            await self._sleep(INTER_REQUEST_SLEEP_SECONDS)
        # Single periodic health summary per read() cycle — best-effort, never
        # raises (Invariant). Placed after the loop so it fires once regardless
        # of how many channels are in `refs`.
        self._emit_health_best_effort()

    async def _read_one(self, ref: SourceRef, since: datetime | None) -> AsyncIterator[RawPost]:
        """Read a single channel once, with FLOOD_WAIT backoff + rotation (AC4).

        A FLOOD_WAIT hint is slept in-task only when short (<= the inline cap);
        a long hint marks the account cooling and retries through
        `_acquire_ready_client`, which rotates to a READY account or aborts the
        ref with `AllAccountsFloodWaitError` (pool=1: the "next" account IS the
        cooling one — sleeping the full hint here parked the collect tick on a
        celery slot for the FLOOD_WAIT's lifetime, the prod hang).

        Auth/ban exceptions (non-flood, non-source-unavailable) trigger a best-effort
        ops self-alert (TASK-035) before re-raising as SourceUnavailableError.
        """
        client = await self._acquire_ready_client()
        try:
            entity = await client.get_entity(ref.handle)
        except Exception as exc:
            if (wait := _flood_wait_seconds(exc)) is not None:
                self._pool.report_flood_wait(retry_after_seconds=wait)
                if wait <= FLOOD_WAIT_INLINE_CAP_SECONDS:
                    await self._sleep(wait)
                async for post in self._read_one(ref, since):
                    yield post
                return
            # Non-flood error on entity resolve (auth/ban/network) — notify ops.
            self._emit_health_best_effort(
                notify_reason="auth_error",
                notify_text=(f"TG pool: account error on entity resolve ({type(exc).__name__})"),
            )
            raise SourceUnavailableError(f"cannot resolve telegram ref {ref.handle}") from exc

        try:
            # Bound the read to a RECENT window, not the full channel history
            # (task-078). Telethon's `offset_date` is EXCLUSIVE and its meaning
            # flips with `reverse`: with the default `reverse=False` it is an
            # UPPER bound and the iterator walks the ENTIRE history backward
            # (task-077: prod posts 2026→2017 → GetHistory flood storms, 100k+
            # buffers, lock held its full TTL). With `reverse=True` it is the
            # LOWER bound and we scan FORWARD from `since` to newest — exactly
            # the recent window we want. `limit=MAX_MESSAGES_PER_TICK` is the
            # hard backstop so even a misconfigured `since` cannot deep-pull.
            # The defensive guard below DROPS anything strictly older than
            # `since`, locking the lower bound at our boundary regardless of
            # server-side off-by-one on the exclusive offset.
            async for message in client.iter_messages(
                entity,
                offset_date=since,
                reverse=True,
                limit=MAX_MESSAGES_PER_TICK,
            ):
                if since is not None and message.date is not None and message.date < since:
                    continue
                yield map_entity(message, ref)
            self._pool.report_success()
        except Exception as exc:
            if (wait := _flood_wait_seconds(exc)) is not None:
                self._pool.report_flood_wait(retry_after_seconds=wait)
                if wait <= FLOOD_WAIT_INLINE_CAP_SECONDS:
                    await self._sleep(wait)
                async for post in self._read_one(ref, since):
                    yield post
                return
            raise SourceUnavailableError(f"failed reading telegram ref {ref.handle}") from exc

    async def _acquire_ready_client(self) -> TelegramClientProtocol:
        """Acquire an account; short full-pool floods back off, long ones abort.

        On AllAccountsFloodWaitError a cooldown within the inline cap is slept
        and retried; a longer cooldown RE-RAISES so the caller skips the ref
        (collect tick logs "source skipped" and moves on) instead of holding the
        task coroutine for the cooldown's lifetime. Pool health metric + ops
        self-alert (TASK-035) are emitted best-effort either way.
        """
        while True:
            try:
                client = self._pool.acquire()
            except AllAccountsFloodWaitError:
                wait = self._pool.cooldown_remaining()
                # Best-effort health metric + ops self-alert (TASK-035, Invariant).
                self._emit_health_best_effort(
                    notify_reason="all_flood",
                    notify_text=(f"TG pool: all accounts flooded. cooldown_remaining={int(wait)}s"),
                )
                if wait > FLOOD_WAIT_INLINE_CAP_SECONDS:
                    raise
                await self._sleep(wait)
                continue
            await _ensure_connected(client)
            return client
