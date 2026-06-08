"""`TelegramCollector` — the Telegram `SourceCollector` (AC2/AC3/AC4/AC5).

Telegram specifics (Telethon errors, entity resolution, iteration) are confined to
this module plus `account_pool`/`mapper`/`dedup`. `read` builds the UNION of unique
refs (cross-tenant dedup), reads each channel once, maps each message via the pure
mapper, and on FLOOD_WAIT applies backoff + account rotation without crashing.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime

from collector.base import RawPost, SourceKind, SourceRef
from collector.constants import INTER_REQUEST_SLEEP_SECONDS
from collector.errors import AllAccountsFloodWaitError, SourceUnavailableError
from collector.telegram.account_pool import AccountPool
from collector.telegram.client import TelegramClientProtocol
from collector.telegram.dedup import normalize_handle, unique_refs
from collector.telegram.mapper import map_entity

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


class TelegramCollector:
    """Telegram implementation of the `SourceCollector` port."""

    kind: SourceKind = SourceKind.TELEGRAM

    def __init__(self, pool: AccountPool, *, sleep: _AsyncSleep | None = None) -> None:
        self._pool = pool
        # Injectable async sleep keeps unit tests instant (no real backoff waits).
        self._sleep: _AsyncSleep = sleep if sleep is not None else asyncio.sleep

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
            await client.connect()
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
        """Yield `RawPost`s for the unique union of `refs` newer than `since` (AC5)."""
        for ref in unique_refs(refs):
            async for post in self._read_one(ref, since):
                yield post
            await self._sleep(INTER_REQUEST_SLEEP_SECONDS)

    async def _read_one(self, ref: SourceRef, since: datetime | None) -> AsyncIterator[RawPost]:
        """Read a single channel once, with FLOOD_WAIT backoff + rotation (AC4)."""
        client = await self._acquire_ready_client()
        try:
            entity = await client.get_entity(ref.handle)
        except Exception as exc:
            if (wait := _flood_wait_seconds(exc)) is not None:
                self._pool.report_flood_wait(retry_after_seconds=wait)
                await self._sleep(wait)
                async for post in self._read_one(ref, since):
                    yield post
                return
            raise SourceUnavailableError(f"cannot resolve telegram ref {ref.handle}") from exc

        try:
            async for message in client.iter_messages(entity, offset_date=since):
                yield map_entity(message, ref)
            self._pool.report_success()
        except Exception as exc:
            if (wait := _flood_wait_seconds(exc)) is not None:
                self._pool.report_flood_wait(retry_after_seconds=wait)
                await self._sleep(wait)
                async for post in self._read_one(ref, since):
                    yield post
                return
            raise SourceUnavailableError(f"failed reading telegram ref {ref.handle}") from exc

    async def _acquire_ready_client(self) -> TelegramClientProtocol:
        """Acquire an account; on full pool flood, back off until one frees up."""
        while True:
            try:
                client = self._pool.acquire()
            except AllAccountsFloodWaitError:
                wait = self._pool.cooldown_remaining()
                await self._sleep(wait)
                continue
            await client.connect()
            return client
