"""PURE mapping: Twitter/X API v2 tweet -> normalized `RawPost` (TASK-031, AC2).

No network, no mutation, no httpx import — we read attributes structurally so the
function is testable on a plain stub. External Twitter data is untrusted: every
field is normalized (tz-aware UTC, integer metrics defaulting to 0 — never `None`,
since the scorer expects numbers).

Metric mapping (research brief §4):
  like_count       -> reactions
  retweet_count    -> forwards
  impression_count -> views     (fallback 0 — not on every access tier)
  reply/quote/bookmark_count -> extra (named int counts, platform-specific)
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol

from collector.base import PostMetrics, RawPost, SourceRef


class TwitterTweet(Protocol):
    """Structural view of the X API v2 tweet attributes the mapper reads.

    Members are read-only properties so an immutable (frozen) DTO like
    `client._Tweet` structurally satisfies the protocol. `public_metrics` is the v2
    metrics object as a mapping of str->int (`like_count`, `retweet_count`,
    `impression_count`, `reply_count`, `quote_count`, `bookmark_count`); `author`
    is the resolved username/handle.
    """

    @property
    def id(self) -> str: ...
    @property
    def text(self) -> str | None: ...
    @property
    def created_at(self) -> datetime | None: ...
    @property
    def author(self) -> str | None: ...
    @property
    def public_metrics(self) -> Mapping[str, int] | None: ...


def _as_int(value: object) -> int:
    """Coerce an optional count to a non-negative int (missing/invalid -> 0)."""
    if isinstance(value, bool):  # bool is an int subclass — exclude explicitly
        return 0
    if isinstance(value, int):
        return max(value, 0)
    return 0


def _utc(value: datetime | None) -> datetime:
    """Return a tz-aware UTC datetime; naive input is assumed UTC."""
    if value is None:
        return datetime.now(tz=UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalize_metrics(public_metrics: Mapping[str, int] | None) -> PostMetrics:
    metrics = public_metrics or {}
    return PostMetrics(
        views=_as_int(metrics.get("impression_count")),
        forwards=_as_int(metrics.get("retweet_count")),
        reactions=_as_int(metrics.get("like_count")),
        extra={
            "reply_count": _as_int(metrics.get("reply_count")),
            "quote_count": _as_int(metrics.get("quote_count")),
            "bookmark_count": _as_int(metrics.get("bookmark_count")),
        },
    )


def map_tweet(tweet: TwitterTweet, source: SourceRef) -> RawPost:
    """Map one X API v2 tweet to a normalized `RawPost` (pure)."""
    return RawPost(
        source=source,
        external_id=str(tweet.id),
        author=tweet.author,
        text=tweet.text or "",
        media_hashes=(),
        metrics=_normalize_metrics(tweet.public_metrics),
        posted_at=_utc(tweet.created_at),
    )
