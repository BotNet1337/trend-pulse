"""`TwitterCollector` — the Twitter/X `SourceCollector` (TASK-031, ADR-001).

Mirrors `collector/telegram/reader.py`. X API specifics (v2 endpoints, 429 reset,
pay-per-use read budget) are confined to this module + `client`/`mapper`/`dedup`.
`read` builds the UNION of unique TWITTER refs, reads each account once newer than
`since`, maps each tweet via the pure mapper, and on 429 applies a bounded inline
backoff (long resets skip the ref) — never crashing the collect tick.

Cost guard (research brief §1): X API is pay-per-use, so a monthly read budget
(`MAX_TWITTER_READS_PER_MONTH`, Redis counter) hard-stops reading and alerts ops
ONCE when exhausted. All self-observation is best-effort and never raises
(Invariant: observation must not crash collection).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypeVar, cast

from collector.base import RawPost, SourceKind, SourceRef
from collector.constants import (
    MAX_TWITTER_READS_PER_MONTH,
    TWITTER_MAX_RESULTS_PER_TICK,
    TWITTER_RATE_LIMIT_INLINE_CAP_SECONDS,
    TWITTER_READS_COUNTER_PREFIX,
)
from collector.errors import (
    SourceUnavailableError,
    TwitterRateLimitError,
    TwitterReadBudgetExceededError,
)
from collector.twitter.client import TwitterClientProtocol
from collector.twitter.dedup import unique_twitter_refs
from collector.twitter.mapper import map_tweet

if TYPE_CHECKING:
    from redis import Redis

    from config import Settings

logger = logging.getLogger(__name__)

_AsyncSleep = Callable[[float], Awaitable[None]]
_T = TypeVar("_T")

# Redis counter lives ~35 days so a month's key self-expires after the month ends.
_READS_COUNTER_TTL_SECONDS = 35 * 24 * 60 * 60


class TwitterCollector:
    """Twitter/X implementation of the `SourceCollector` port."""

    kind: SourceKind = SourceKind.TWITTER

    def __init__(
        self,
        client: TwitterClientProtocol,
        *,
        sleep: _AsyncSleep | None = None,
        settings: Settings | None = None,
        redis: Redis | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._sleep: _AsyncSleep = sleep if sleep is not None else asyncio.sleep
        self._settings = settings
        self._redis = redis
        # Injectable clock so the month-bucket key is deterministic in tests.
        self._now: Callable[[], datetime] = now if now is not None else (lambda: datetime.now(UTC))
        # Month bucket (YYYY-MM) we've already alerted for — so the budget alert
        # fires once PER MONTH, not once per process lifetime (the collector is a
        # cached singleton that can outlive a month rollover).
        self._budget_alerted_month = ""

    async def aclose(self) -> None:
        """Release the underlying client transport (worker shutdown)."""
        await self._client.aclose()

    async def __aenter__(self) -> TwitterCollector:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def validate_ref(self, ref: SourceRef) -> bool:
        """True iff `ref` resolves to a readable public account; never raises (ADR-001)."""
        if ref.kind is not SourceKind.TWITTER:
            return False
        from collector.twitter.dedup import normalize_handle

        handle = normalize_handle(ref.handle)
        try:
            user_id = await self._client.resolve_user_id(handle)
        except Exception:
            # Rate-limited / network / API error — cannot confirm now, not validated.
            logger.info("twitter validate_ref could not confirm handle")
            return False
        return user_id is not None

    async def read(self, refs: list[SourceRef], since: datetime | None) -> AsyncIterator[RawPost]:
        """Yield `RawPost`s for the unique union of TWITTER `refs` newer than `since`."""
        for ref in unique_twitter_refs(refs):
            self._guard_read_budget()
            async for post in self._read_one(ref, since):
                yield post

    async def _read_one(self, ref: SourceRef, since: datetime | None) -> AsyncIterator[RawPost]:
        """Read one account once, with bounded 429 backoff (long resets skip the ref)."""
        user_id = await self._with_rate_limit(lambda: self._client.resolve_user_id(ref.handle), ref)
        if user_id is None:
            return  # private / nonexistent / renamed — skip silently (like validate)

        tweets = await self._with_rate_limit(
            lambda: self._client.fetch_tweets(
                user_id,
                start_time=since,
                max_results=TWITTER_MAX_RESULTS_PER_TICK,
                author=ref.handle,
            ),
            ref,
        )
        self._charge_read_budget(len(tweets))
        for tweet in tweets:
            # `start_time` already bounds the API result; double-guard the cutoff.
            if since is not None and tweet.created_at is not None and tweet.created_at < since:
                continue
            yield map_tweet(tweet, ref)

    async def _with_rate_limit(self, op: Callable[[], Awaitable[_T]], ref: SourceRef) -> _T:
        """Run `op`; on 429 sleep a short reset and retry ONCE, else skip the ref.

        EVERY failure is converted to `SourceUnavailableError` so a single bad
        account (429, API 5xx, network/JSON error) skips ONLY that ref — the
        collect tick catches `SourceUnavailableError` and keeps the rest going
        (Invariant: a failing ref never kills the rest). A long 429 reset (above the
        inline cap) skips immediately so the tick coroutine is never parked for the
        full reset window (mirrors the Telegram FLOOD pattern).
        """
        try:
            return await op()
        except TwitterRateLimitError as exc:
            wait = exc.retry_after_seconds
            if wait > TWITTER_RATE_LIMIT_INLINE_CAP_SECONDS:
                raise SourceUnavailableError(
                    f"twitter rate-limited for {ref.handle} (reset {int(wait)}s) — skip ref"
                ) from exc
            await self._sleep(wait)
            try:
                return await op()
            except Exception as exc2:  # 2nd 429 or any other error → skip the ref
                raise SourceUnavailableError(
                    f"twitter retry failed for {ref.handle} ({type(exc2).__name__}) — skip ref"
                ) from exc2
        except Exception as exc:
            # API 5xx / network / malformed-JSON — skip ONLY this ref, never crash
            # the tick (the outer collect_tick catches SourceUnavailableError).
            raise SourceUnavailableError(
                f"twitter error for {ref.handle} ({type(exc).__name__}) — skip ref"
            ) from exc

    # --- read budget (pay-per-use spend backstop) --------------------------------

    def _current_month(self) -> str:
        return self._now().strftime("%Y-%m")

    def _counter_key(self) -> str:
        return f"{TWITTER_READS_COUNTER_PREFIX}:{self._current_month()}"

    def _reads_this_month(self) -> int:
        """Best-effort current-month read count (0 when Redis absent/unreachable)."""
        if self._redis is None:
            return 0
        try:
            # redis-py sync stubs type returns as Any|Awaitable; we use the sync
            # client, so cast at this single seam (same pattern as collector.tasks).
            raw = cast("bytes | str | None", self._redis.get(self._counter_key()))
        except Exception:
            return 0
        if raw is None:
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    def _guard_read_budget(self) -> None:
        """Stop reading + alert ops ONCE when the monthly read budget is exhausted."""
        if self._reads_this_month() < MAX_TWITTER_READS_PER_MONTH:
            return
        current_month = self._current_month()
        if self._budget_alerted_month != current_month:
            self._budget_alerted_month = current_month
            self._notify_ops_best_effort(
                reason="twitter_read_budget",
                text=(
                    "Twitter: месячный лимит чтений "
                    f"({MAX_TWITTER_READS_PER_MONTH}) исчерпан — ингест Twitter остановлен "
                    "до следующего месяца (защита от расхода)."
                ),
            )
        raise TwitterReadBudgetExceededError("twitter monthly read budget exhausted")

    def _charge_read_budget(self, count: int) -> None:
        """Increment the monthly read counter best-effort (never raises).

        INCRBY + EXPIRE are issued in ONE pipeline so the TTL can never be lost to a
        crash between the two commands (the month key would otherwise leak forever).
        Re-setting EXPIRE on every charge is idempotent and keeps the key alive for
        the whole month.
        """
        if self._redis is None or count <= 0:
            return
        try:
            pipe = self._redis.pipeline()
            pipe.incrby(self._counter_key(), count)
            pipe.expire(self._counter_key(), _READS_COUNTER_TTL_SECONDS)
            pipe.execute()
        except Exception:
            logger.warning("twitter read-budget counter update failed (ignored)")

    def _notify_ops_best_effort(self, *, reason: str, text: str) -> None:
        """Send an ops self-alert (best-effort, never raises) — reuses notify_ops."""
        if self._settings is None or self._redis is None:
            return
        try:
            from observability.pool_health import notify_ops

            notify_ops(reason=reason, text=text, settings=self._settings, redis=self._redis)
        except Exception as exc:
            logger.warning("twitter ops alert failed", extra={"exc_type": type(exc).__name__})
