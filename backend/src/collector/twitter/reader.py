"""`TwitterCollector` — the Twitter/X `SourceCollector` (TASK-031, ADR-001).

Mirrors `collector/telegram/reader.py`. X API specifics (v2 endpoints, 429 reset,
402 credits, pay-per-use read budget) are confined to this module + `client`/
`mapper`/`dedup`. `read` builds the UNION of unique TWITTER refs, reads each account
once newer than `since`, maps each tweet via the pure mapper, and never crashes the
collect tick (any failure skips ONLY that ref via `SourceUnavailableError`).

Cost controls (research brief §1 — X API is pay-per-use, $0.005/read):
- **Per-account read interval**: the shared collect tick fires ~every 60s and reads
  all kinds; we read each Twitter account at most once per
  `TWITTER_MIN_READ_INTERVAL_SECONDS` (Redis last-read stamp) so the 15-min cadence
  is real regardless of the tick frequency.
- **user-id cache**: resolve is itself billable; ids are stable → cached in Redis.
- **monthly read budget**: hard stop + once/month ops alert at
  `MAX_TWITTER_READS_PER_MONTH`.
- **402 credits cooldown**: on CreditsDepleted, pause ALL reads for
  `TWITTER_CREDITS_COOLDOWN_SECONDS` and alert ops once (a persistent billing state).

All self-observation is best-effort and never raises (Invariant).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, TypeVar, cast

from collector.base import RawPost, SourceKind, SourceRef
from collector.constants import (
    MAX_TWITTER_READS_PER_MONTH,
    TWITTER_CREDITS_COOLDOWN_SECONDS,
    TWITTER_LASTREAD_PREFIX,
    TWITTER_MAX_RESULTS_PER_TICK,
    TWITTER_MIN_READ_INTERVAL_SECONDS,
    TWITTER_RATE_LIMIT_INLINE_CAP_SECONDS,
    TWITTER_RATE_LIMIT_PAUSE_CAP_SECONDS,
    TWITTER_READS_COUNTER_PREFIX,
    TWITTER_USERID_PREFIX,
    TWITTER_USERID_TTL_SECONDS,
)
from collector.errors import (
    SourceUnavailableError,
    TwitterCreditsDepletedError,
    TwitterRateLimitError,
    TwitterReadBudgetExceededError,
)
from collector.twitter.client import TwitterClientProtocol
from collector.twitter.dedup import normalize_handle, unique_twitter_refs
from collector.twitter.mapper import map_tweet

if TYPE_CHECKING:
    from redis import Redis

    from config import Settings

logger = logging.getLogger(__name__)

_AsyncSleep = Callable[[float], Awaitable[None]]
_T = TypeVar("_T")

# Redis counter lives ~35 days so a month's key self-expires after the month ends.
_READS_COUNTER_TTL_SECONDS = 35 * 24 * 60 * 60
# Last-read stamp lives a few intervals so a quiet account eventually re-reads.
_LASTREAD_TTL_SECONDS = max(TWITTER_MIN_READ_INTERVAL_SECONDS * 4, 3600)


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
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._client = client
        self._sleep: _AsyncSleep = sleep if sleep is not None else asyncio.sleep
        self._settings = settings
        self._redis = redis
        # Injectable clocks so month bucket + cooldown are deterministic in tests.
        self._now: Callable[[], datetime] = now if now is not None else (lambda: datetime.now(UTC))
        self._monotonic: Callable[[], float] = (
            monotonic if monotonic is not None else time.monotonic
        )
        # Month bucket already alerted for the read budget (once per month).
        self._budget_alerted_month = ""
        # Monotonic deadline until which ALL Twitter reads are paused (402 credits or
        # a long 429 rate-limit) — avoids hammering the API account-by-account.
        self._pause_until = 0.0

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
        handle = normalize_handle(ref.handle)
        try:
            user_id = await self._client.resolve_user_id(handle)
        except Exception:
            # Rate-limited / credits / network / API error — cannot confirm now.
            logger.info("twitter validate_ref could not confirm handle")
            return False
        return user_id is not None

    async def read(self, refs: list[SourceRef], since: datetime | None) -> AsyncIterator[RawPost]:
        """Yield `RawPost`s for the unique union of TWITTER `refs` newer than `since`."""
        if self._in_pause():
            # Paused (no credits / rate-limited) — do not touch the API this tick.
            return
        for ref in unique_twitter_refs(refs):
            self._guard_read_budget()
            async for post in self._read_one(ref, since):
                yield post

    async def _read_one(self, ref: SourceRef, since: datetime | None) -> AsyncIterator[RawPost]:
        """Read one account once (cost-guarded), with bounded 429 backoff."""
        # Per-account cadence: skip accounts read within the min interval (no API call).
        if not self._should_read_account(ref.handle):
            return
        # Stamp the attempt window from the PREVIOUS read, then mark NOW — so a
        # failing account (402/429/dead) is NOT re-polled every 60s tick (cost +
        # rate-limit safety). Applies on success AND failure.
        effective_since = self._effective_since(ref.handle, since)
        self._mark_account_read(ref.handle)
        try:
            user_id = await self._resolve_user_id_cached(ref)
            if user_id is None:
                return  # private / nonexistent / renamed — skip silently
            tweets = await self._with_rate_limit(
                lambda: self._client.fetch_tweets(
                    user_id,
                    start_time=effective_since,
                    max_results=TWITTER_MAX_RESULTS_PER_TICK,
                    author=ref.handle,
                ),
                ref,
            )
        except TwitterCreditsDepletedError as exc:
            self._enter_pause(
                TWITTER_CREDITS_COOLDOWN_SECONDS,
                reason="twitter_credits",
                text=(
                    "Twitter: нет кредитов на X API (HTTP 402 CreditsDepleted) — ингест "
                    f"Twitter на паузе {TWITTER_CREDITS_COOLDOWN_SECONDS // 60} мин. "
                    "Пополни баланс X API."
                ),
                alert=True,
            )
            raise SourceUnavailableError(
                f"twitter credits depleted while reading {ref.handle} — paused"
            ) from exc
        self._charge_read_budget(len(tweets))
        for tweet in tweets:
            # No post-loop date filter: `start_time=effective_since` already bounds
            # the API result to the window we queried. A previous double-guard filtered
            # by the caller's ~60s tick `since` (NOT effective_since) and discarded
            # every tweet the wider window fetched → every read yielded 0 posts in prod.
            yield map_tweet(tweet, ref)

    async def _resolve_user_id_cached(self, ref: SourceRef) -> str | None:
        """Resolve handle→id, caching in Redis (resolve is itself a billable read)."""
        cached = self._cached_user_id(ref.handle)
        if cached is not None:
            return cached
        user_id = await self._with_rate_limit(lambda: self._client.resolve_user_id(ref.handle), ref)
        if user_id is not None:
            self._cache_user_id(ref.handle, user_id)
        return user_id

    async def _with_rate_limit(self, op: Callable[[], Awaitable[_T]], ref: SourceRef) -> _T:
        """Run `op`; on 429 sleep a short reset and retry ONCE, else skip the ref.

        429 / API / network / JSON errors become `SourceUnavailableError` (per-ref
        skip — never crash the tick). `TwitterCreditsDepletedError` is re-raised so
        the caller can enter the billing cooldown instead of treating it as a normal
        per-ref miss.
        """
        try:
            return await op()
        except TwitterCreditsDepletedError:
            raise
        except TwitterRateLimitError as exc:
            wait = exc.retry_after_seconds
            if wait > TWITTER_RATE_LIMIT_INLINE_CAP_SECONDS:
                # Long reset → PAUSE all reads until it clears (don't let the other
                # accounts each hit 429 this tick). No ops alert (rate-limit is
                # expected/transient), just a throttled-by-cooldown pause.
                self._enter_pause(
                    min(wait, TWITTER_RATE_LIMIT_PAUSE_CAP_SECONDS),
                    reason="twitter_rate_limit",
                    text="",
                    alert=False,
                )
                raise SourceUnavailableError(
                    f"twitter rate-limited for {ref.handle} (reset {int(wait)}s) — paused"
                ) from exc
            await self._sleep(wait)
            try:
                return await op()
            except TwitterCreditsDepletedError:
                raise
            except Exception as exc2:
                raise SourceUnavailableError(
                    f"twitter retry failed for {ref.handle} ({type(exc2).__name__}) — skip ref"
                ) from exc2
        except Exception as exc:
            raise SourceUnavailableError(
                f"twitter error for {ref.handle} ({type(exc).__name__}) — skip ref"
            ) from exc

    # --- global pause (402 credits / long 429 rate-limit) -------------------------

    def _in_pause(self) -> bool:
        return self._monotonic() < self._pause_until

    def _enter_pause(self, seconds: float, *, reason: str, text: str, alert: bool) -> None:
        """Pause ALL Twitter reads for `seconds`; alert ops ONCE on first entry.

        Used for both 402 CreditsDepleted (alert=True) and a long 429 rate-limit
        (alert=False — expected/transient). Extends an existing pause, never shortens.
        """
        was_paused = self._in_pause()
        self._pause_until = max(self._pause_until, self._monotonic() + seconds)
        if alert and not was_paused:
            self._notify_ops_best_effort(reason=reason, text=text)

    # --- per-account cadence + user-id cache --------------------------------------

    def _now_epoch(self) -> float:
        return self._now().timestamp()

    def _should_read_account(self, handle: str) -> bool:
        """True unless this account was read within the min interval (Redis stamp)."""
        if self._redis is None:
            return True
        try:
            raw = cast("bytes | str | None", self._redis.get(f"{TWITTER_LASTREAD_PREFIX}:{handle}"))
        except Exception:
            return True
        if raw is None:
            return True
        try:
            last = float(raw)
        except (TypeError, ValueError):
            return True
        return (self._now_epoch() - last) >= TWITTER_MIN_READ_INTERVAL_SECONDS

    def _mark_account_read(self, handle: str) -> None:
        if self._redis is None:
            return
        try:
            key = f"{TWITTER_LASTREAD_PREFIX}:{handle}"
            self._redis.set(key, str(self._now_epoch()), ex=_LASTREAD_TTL_SECONDS)
        except Exception:
            logger.warning("twitter lastread stamp update failed (ignored)")

    def _effective_since(self, handle: str, caller_since: datetime | None) -> datetime | None:
        """Read window for this account: since its previous read, with a min lookback.

        Twitter accounts post infrequently, and the shared collect tick's `since` is
        only ~60s old — too narrow to catch anything. So the window floors to one
        read-interval (`now - TWITTER_MIN_READ_INTERVAL_SECONDS`): on the FIRST read
        of an account (no stamp) AND in steady state (stamp ~one interval old) this
        captures the whole period since we last looked. An even older `caller_since`
        (outage catch-up) widens it further. `max_results` caps the cost regardless.
        """
        floor = self._now() - timedelta(seconds=TWITTER_MIN_READ_INTERVAL_SECONDS)
        base = floor
        if self._redis is not None:
            try:
                raw = cast(
                    "bytes | str | None",
                    self._redis.get(f"{TWITTER_LASTREAD_PREFIX}:{handle}"),
                )
                if raw is not None:
                    base = datetime.fromtimestamp(float(raw), tz=UTC)
            except Exception:
                base = floor
        # Never start NEWER than one interval ago; honor an older caller_since.
        candidates = [base, floor]
        if caller_since is not None:
            candidates.append(caller_since)
        return min(candidates)

    def _cached_user_id(self, handle: str) -> str | None:
        if self._redis is None:
            return None
        try:
            raw = cast("bytes | str | None", self._redis.get(f"{TWITTER_USERID_PREFIX}:{handle}"))
        except Exception:
            return None
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else str(raw)

    def _cache_user_id(self, handle: str, user_id: str) -> None:
        if self._redis is None:
            return
        try:
            self._redis.set(
                f"{TWITTER_USERID_PREFIX}:{handle}", user_id, ex=TWITTER_USERID_TTL_SECONDS
            )
        except Exception:
            logger.warning("twitter user-id cache update failed (ignored)")

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
        """Stop reading + alert ops ONCE per month when the read budget is exhausted."""
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

        INCRBY + EXPIRE in ONE pipeline so the TTL can't be lost to a crash between
        commands. Re-setting EXPIRE each charge is idempotent (keeps the month key
        alive for the month).
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
