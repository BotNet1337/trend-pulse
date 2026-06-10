"""Showcase post text builder + topic sanitization (TASK-044).

`build_showcase_post(topic, score, first_seen, public_base_url)` produces the
TG message text:

    🔥 {topic} · score {N} · обнаружено в {HH:MM} UTC
    {public_base_url}/?utm_source=tg_showcase&utm_campaign=autopost

`sanitize_topic(raw)` strips URLs, @-handles, and email addresses from a raw
cluster topic string before it appears in public text. The implementation
delegates to `textutils.sanitize_topic_label` — a shared, neutral module that
has no domain imports (no API/showcase/alerts) and is safe to import from any
layer without creating cycles.

Design:
- Pure functions (no I/O, no DB) → trivially testable.
- score displayed as integer when it is a whole number (94.0 → "94"), otherwise
  one decimal place (94.5 → "94.5") — clean display.
- CTA URL is NOT interpolated from user input — public_base_url comes from
  Settings (validated; compliance §7).
"""

from __future__ import annotations

from datetime import UTC, datetime

# Shared compliance-hardened sanitization (TASK-044 layering fix).
# textutils has no domain imports — safe from any layer, no cycles.
from textutils import sanitize_topic_label as _sanitize_impl

# CTA query string — fixed, no user-input interpolation (compliance §7 / security).
_UTM_SUFFIX: str = "?utm_source=tg_showcase&utm_campaign=autopost"


def sanitize_topic(raw: str) -> str:
    """Return a sanitized display label from a raw cluster topic string.

    Strips URLs (http/https/t.me), @-handles, and email addresses, then
    collapses whitespace and caps length.  Delegates to
    `textutils.sanitize_topic_label`.

    Args:
        raw: Raw cluster topic string (may contain URLs, handles, etc.).

    Returns:
        Sanitized human-readable label (no raw content).
    """
    return _sanitize_impl(raw)


def build_showcase_post(
    *,
    topic: str,
    score: float,
    first_seen: datetime,
    public_base_url: str,
) -> str:
    """Build the TG post text for a showcase cluster.

    Format:
        🔥 {topic} · score {N} · обнаружено в {HH:MM} UTC
        {public_base_url}/?utm_source=tg_showcase&utm_campaign=autopost

    Args:
        topic:          Sanitized cluster topic label (caller must sanitize first).
        score:          Viral score (float).
        first_seen:     Cluster first_seen datetime (UTC); used for the timestamp stamp.
        public_base_url: Base URL of the public deployment (from Settings).

    Returns:
        Post text string (no raw content — aggregate only, compliance §7).
    """
    # Ensure first_seen is UTC-aware for strftime.
    ts = first_seen
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)

    time_stamp = ts.strftime("%H:%M")

    # Score display: integer when whole, one decimal otherwise.
    score_str = str(int(score)) if score == int(score) else f"{score:.1f}"

    cta = f"{public_base_url.rstrip('/')}/{_UTM_SUFFIX}"

    return f"🔥 {topic} · score {score_str} · обнаружено в {time_stamp} UTC\n{cta}"
