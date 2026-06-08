"""Platform-independent source-abstraction core (ADR-001).

This module is the multi-source seam: pipeline/scorer depend ONLY on the types
here (`RawPost`/`PostMetrics`) and never on a concrete platform. Adding a source
(Twitter/X, ...) means a new `SourceCollector` implementation — these contracts
do not change.

CRITICAL: this module MUST NOT import telethon (or any platform SDK). Keeping the
core SDK-free is what lets pipeline tests run on `RawPost` fixtures alone.
"""

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable


class SourceKind(StrEnum):
    """Platform a reference belongs to. Telegram now; Twitter/X later (ADR-001)."""

    TELEGRAM = "telegram"
    TWITTER = "twitter"  # future marker — declared, not implemented (ADR-001 scope guard)


@dataclass(frozen=True)
class SourceRef:
    """What we monitor: a platform `kind` + its `handle` (channel/account/tag)."""

    kind: SourceKind
    handle: str


@dataclass(frozen=True)
class PostMetrics:
    """Engagement metrics normalized across platforms.

    `views`/`forwards`/`reactions` are the common numeric shape the scorer reads
    (always integers, never `None`). Platform-specific numeric signals live in
    `extra` (a read-only mapping of named integer counts) so the common shape
    stays platform-independent.
    """

    views: int
    forwards: int
    reactions: int
    extra: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class RawPost:
    """A normalized post from any source (ADR-001).

    `external_id` dedups within a source; `media_hashes` are perceptual/content
    hashes (empty tuple when none); `posted_at` is always tz-aware UTC.
    """

    source: SourceRef
    external_id: str
    author: str | None
    text: str | None
    media_hashes: tuple[str, ...]
    metrics: PostMetrics
    posted_at: datetime


@runtime_checkable
class SourceCollector(Protocol):
    """Port every source adapter implements (ADR-001).

    Rate-limiting, backoff and account rotation are encapsulated INSIDE the
    implementation and never surface through this interface.
    """

    kind: SourceKind

    async def validate_ref(self, ref: SourceRef) -> bool:
        """True iff `ref` is a readable public reference; never raises outward."""
        ...

    def read(self, refs: list[SourceRef], since: datetime | None) -> AsyncIterator[RawPost]:
        """Yield normalized posts for the unique union of `refs` newer than `since`."""
        ...
