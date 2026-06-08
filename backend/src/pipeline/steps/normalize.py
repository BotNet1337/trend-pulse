"""Text normalization → `NormalizedPost` (task-007 step 2, AC2).

Pure + immutable: ``run`` returns a NEW list of frozen `NormalizedPost`; the input
`RawPost`s are never mutated. Cleaning strips URLs, markdown emphasis markup and
emoji/symbol characters, then collapses whitespace. Translation is a deliberate
no-op seam (passthrough) — we do not pull in a translation dependency on this task
(see task doc Discussion: translation behind the step interface, default
passthrough). Platform-independent: operates on the ADR-001 `RawPost` only.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from collector.base import PostMetrics, RawPost, SourceRef

# Inline-markdown / URL stripping. Compiled once at import (cheap, no model load).
_URL_RE = re.compile(r"https?://\S+|www\.\S+|t\.me/\S+")
# Markdown emphasis + inline-code markers (*, _, `, ~) and heading/quote markers.
_MARKUP_RE = re.compile(r"[*_`~#>]+")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class NormalizedPost:
    """A cleaned, platform-independent post carried through embed/cluster.

    Frozen (immutable): produced anew by `normalize.run`, never edited in place.
    Carries the provenance needed to persist clusters (`source`/`external_id`) plus
    the cleaned `text`, the original `metrics` and tz-aware `posted_at` (the scorer
    and cluster aggregation read these). `text` is always a `str` (possibly empty).
    """

    source: SourceRef
    external_id: str
    text: str
    metrics: PostMetrics
    posted_at: datetime


def _strip_emoji(text: str) -> str:
    """Drop emoji/symbol/pictograph code points (Unicode category 'So'/'Sk')."""
    return "".join(ch for ch in text if unicodedata.category(ch) not in {"So", "Sk"})


def clean_text(text: str | None) -> str:
    """Clean raw post text: strip URLs, markup, emoji; collapse whitespace.

    `None`/empty text normalizes to an empty string (never raises) — an empty post
    is a valid edge case the downstream steps must tolerate.
    """
    if not text:
        return ""
    without_urls = _URL_RE.sub(" ", text)
    without_markup = _MARKUP_RE.sub(" ", without_urls)
    without_emoji = _strip_emoji(without_markup)
    return _WHITESPACE_RE.sub(" ", without_emoji).strip()


def run(posts: list[RawPost]) -> list[NormalizedPost]:
    """Return a NEW list of `NormalizedPost` with cleaned text; inputs untouched."""
    return [
        NormalizedPost(
            source=post.source,
            external_id=post.external_id,
            text=clean_text(post.text),
            metrics=post.metrics,
            posted_at=post.posted_at,
        )
        for post in posts
    ]
