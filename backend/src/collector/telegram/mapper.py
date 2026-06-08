"""PURE mapping: Telegram `Message` -> normalized `RawPost` (AC1).

No network, no mutation, no telethon import (we read attributes structurally so
the function is testable on a plain stub). External Telegram data is untrusted:
every field is normalized (tz-aware UTC, integer metrics defaulting to 0 — never
`None`, since the scorer expects numbers).
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol

from collector.base import PostMetrics, RawPost, SourceRef


class _ReactionCount(Protocol):
    count: int | None


class _Reactions(Protocol):
    results: Sequence[_ReactionCount]


class TelegramMessage(Protocol):
    """Structural view of the Telethon `Message` attributes the mapper reads.

    Public (shared with the transport layer) so `iter_messages` can be typed as
    yielding the exact shape `map_entity` consumes — no `Any`, no coupling to the
    concrete Telethon class.
    """

    id: int
    message: str | None
    views: int | None
    forwards: int | None
    reactions: _Reactions | None
    date: datetime | None
    post_author: str | None


def _as_int(value: int | None) -> int:
    """Coerce an optional count to a non-negative int (missing -> 0)."""
    return int(value) if value is not None else 0


def _utc(value: datetime | None) -> datetime:
    """Return a tz-aware UTC datetime; naive input is assumed UTC."""
    if value is None:
        return datetime.now(tz=UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalize_reactions(reactions: _Reactions | None) -> tuple[int, int]:
    """Return (total reaction count, distinct reaction kinds)."""
    if reactions is None:
        return 0, 0
    results = getattr(reactions, "results", None) or []
    total = sum(_as_int(getattr(r, "count", 0)) for r in results)
    return total, len(results)


def _normalize_metrics(message: TelegramMessage) -> PostMetrics:
    reactions_total, reaction_kinds = _normalize_reactions(message.reactions)
    return PostMetrics(
        views=_as_int(message.views),
        forwards=_as_int(message.forwards),
        reactions=reactions_total,
        extra={"reaction_kinds": reaction_kinds},
    )


def map_entity(message: TelegramMessage, source: SourceRef) -> RawPost:
    """Map one Telegram message to a normalized `RawPost` (pure)."""
    return RawPost(
        source=source,
        external_id=str(message.id),
        author=message.post_author,
        text=message.message or "",
        media_hashes=(),
        metrics=_normalize_metrics(message),
        posted_at=_utc(message.date),
    )
