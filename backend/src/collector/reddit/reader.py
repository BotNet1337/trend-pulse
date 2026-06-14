"""`RedditCollector` — the Reddit `SourceCollector` (TASK-092, ADR-001).

Mirrors `collector/twitter/reader.py`, but SIMPLER: Reddit OAuth2 application-only
read access is FREE (no per-read price), so there is NO monthly read budget, no
user-id cache and no 402 credits cooldown — only rate-limit-aware backoff. Reddit
API specifics (OAuth2 token refresh, `/r/{sub}/about`, `/r/{sub}/new`, 429 reset)
are confined to this module + `client`/`mapper`/`dedup`.

`read` builds the UNION of unique REDDIT refs, reads each subreddit's newest
submissions, filters by `since`, maps each via the pure mapper, and on a short 429
applies a bounded inline backoff (a long reset skips the ref) — never crashing the
collect tick (any failure skips ONLY that ref via `SourceUnavailableError`).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import TypeVar

from collector.base import RawPost, SourceKind, SourceRef
from collector.constants import (
    REDDIT_MAX_RESULTS_PER_TICK,
    REDDIT_RATE_LIMIT_INLINE_CAP_SECONDS,
)
from collector.errors import RedditRateLimitError, SourceUnavailableError
from collector.reddit.client import RedditClientProtocol, _Submission
from collector.reddit.dedup import normalize_handle, unique_reddit_refs
from collector.reddit.mapper import map_submission

logger = logging.getLogger(__name__)

_AsyncSleep = Callable[[float], Awaitable[None]]
_T = TypeVar("_T")


class RedditCollector:
    """Reddit implementation of the `SourceCollector` port."""

    kind: SourceKind = SourceKind.REDDIT

    def __init__(
        self,
        client: RedditClientProtocol,
        *,
        sleep: _AsyncSleep | None = None,
    ) -> None:
        self._client = client
        self._sleep: _AsyncSleep = sleep if sleep is not None else asyncio.sleep

    async def aclose(self) -> None:
        """Release the underlying client transport (worker shutdown)."""
        await self._client.aclose()

    async def __aenter__(self) -> RedditCollector:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def validate_ref(self, ref: SourceRef) -> bool:
        """True iff `ref` is a readable public subreddit; never raises (ADR-001)."""
        if ref.kind is not SourceKind.REDDIT:
            return False
        name = normalize_handle(ref.handle)
        try:
            return await self._client.subreddit_exists(name)
        except Exception as exc:
            # Rate-limited / auth / network / API error — cannot confirm now. The
            # subreddit name is not a secret; the exception body might be, so log
            # only its type (never `str(exc)`).
            logger.info(
                "reddit validate_ref could not confirm subreddit",
                extra={"handle": name, "exc_type": type(exc).__name__},
            )
            return False

    async def read(self, refs: list[SourceRef], since: datetime | None) -> AsyncIterator[RawPost]:
        """Yield `RawPost`s for the unique union of REDDIT `refs` newer than `since`."""
        for ref in unique_reddit_refs(refs):
            async for post in self._read_one(ref, since):
                yield post

    async def _read_one(self, ref: SourceRef, since: datetime | None) -> AsyncIterator[RawPost]:
        """Read one subreddit's newest submissions, with bounded 429 backoff."""
        submissions = await self._with_rate_limit(
            lambda: self._client.fetch_new(ref.handle, limit=REDDIT_MAX_RESULTS_PER_TICK),
            ref,
        )
        for submission in submissions:
            # `/r/{sub}/new` returns newest-first; guard the cutoff per-submission.
            if (
                since is not None
                and submission.created_utc is not None
                and submission.created_utc < since
            ):
                continue
            yield map_submission(submission, ref)

    async def _with_rate_limit(
        self, op: Callable[[], Awaitable[list[_Submission]]], ref: SourceRef
    ) -> list[_Submission]:
        """Run `op`; on a short 429 sleep the reset and retry ONCE, else skip the ref.

        429 / auth / API / network / JSON errors become `SourceUnavailableError`
        (per-ref skip — never crash the tick).
        """
        try:
            return await op()
        except RedditRateLimitError as exc:
            wait = exc.retry_after_seconds
            if wait > REDDIT_RATE_LIMIT_INLINE_CAP_SECONDS:
                raise SourceUnavailableError(
                    f"reddit rate-limited for {ref.handle} (reset {int(wait)}s) — skip ref"
                ) from exc
            await self._sleep(wait)
            try:
                return await op()
            except Exception as exc2:
                raise SourceUnavailableError(
                    f"reddit retry failed for {ref.handle} ({type(exc2).__name__}) — skip ref"
                ) from exc2
        except Exception as exc:
            raise SourceUnavailableError(
                f"reddit error for {ref.handle} ({type(exc).__name__}) — skip ref"
            ) from exc
