"""Shared text utility helpers (TASK-044).

`sanitize_topic_label(raw)` — strips URLs, @-handles, and email addresses from a
raw cluster topic string.  Extracted here so both `api.trending.service` and
`showcase.formatting` can import from a neutral, non-circular location instead of
showcase importing a private symbol from an API-layer module.

Layer hierarchy: this module has NO imports from any domain module (api/, showcase/,
alerts/, etc.) and may be imported from any layer without risk of cycles.
"""

from __future__ import annotations

import re

# Maximum character length for a sanitized topic display label.
# Matches TRENDING_LABEL_MAX_LEN in api.trending.service — kept in sync via the
# named constant imported by that module.
TOPIC_LABEL_MAX_LEN: int = 80

# Regex matching tokens that leak raw content (URLs, @-handles, emails).
# Order: URL pattern first (most specific — captures email-in-URL too); then
# standalone emails; then @-handles.
_RAW_CONTENT_RE = re.compile(
    r"https?://\S+"  # http/https URLs
    r"|t\.me/\S+"  # bare t.me links (no scheme)
    r"|\S+@\S+\.\S+"  # email addresses
    r"|@\w+",  # @-handles
    re.IGNORECASE,
)


def sanitize_topic_label(raw: str) -> str:
    """Return a safe display label from a raw cluster topic string.

    Strips URLs (http/https/t.me), @-handles, and email addresses, then
    collapses runs of whitespace to a single space and caps the result to
    TOPIC_LABEL_MAX_LEN characters (with ellipsis if truncated).

    This is the compliance §7 sanitization (AC5 TASK-039/044): ``clusters.topic``
    may be raw post text; only a clean aggregate label is returned to callers.

    Args:
        raw: The raw ``clusters.topic`` value (centroid label from pipeline).

    Returns:
        A sanitized, human-readable display label ≤ TOPIC_LABEL_MAX_LEN chars.
    """
    cleaned = _RAW_CONTENT_RE.sub("", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > TOPIC_LABEL_MAX_LEN:
        cleaned = cleaned[: TOPIC_LABEL_MAX_LEN - 1].rstrip() + "…"
    return cleaned
