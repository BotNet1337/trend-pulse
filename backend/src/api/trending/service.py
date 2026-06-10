"""Trending domain service (TASK-039).

`get_trending(session, pack_slug, limit) -> TrendingResponse`

Queries the showcase tenant's clusters + scores:
  - Joins clusters with scores on (user_id, cluster_id).
  - Filters: user_id = showcase_user_id, topic = pack.topic, window = 24h.
  - Orders by viral_score DESC, limit to TOP_K.
  - Returns aggregate-only fields (no raw content, compliance §7).

warming_up semantics:
  True  → showcase user absent OR has zero clusters at all.
  False → showcase is warmed (≥1 cluster exists), even if 0 results for this pack/window.

Topic sanitization (compliance §7, AC5):
  `clusters.topic` may contain raw post text (pipeline cluster.py uses post.text[:255]
  as the centroid label). Before returning it via the API, `_sanitize_topic_label()`
  strips URLs, @-handles, emails, and collapses whitespace, capping the result to
  TRENDING_LABEL_MAX_LEN characters. This keeps the public endpoint aggregate-only.
"""

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.packs.data import get_pack
from api.trending.schemas import TrendingItem, TrendingResponse
from config import get_settings
from storage.models.clusters import Cluster
from storage.models.scores import Score
from storage.models.users import User

# Maximum character length for the sanitized topic display label returned in
# TrendingItem.topic. Longer strings are truncated with an ellipsis.
# Named constant (CONVENTIONS: no magic literals).
TRENDING_LABEL_MAX_LEN: int = 80

# Regex matching tokens that leak raw content (URLs, @-handles, emails).
# Order matters: URL pattern is most specific and must come first so that
# e-mail addresses (which contain @) are also removed by the URL branch when
# they appear inside URLs; standalone emails follow; then @-handles.
_RAW_CONTENT_RE = re.compile(
    r"https?://\S+"  # http/https URLs
    r"|t\.me/\S+"  # bare t.me links (no scheme)
    r"|\S+@\S+\.\S+"  # email addresses
    r"|@\w+",  # @-handles
    re.IGNORECASE,
)


def _sanitize_topic_label(raw: str) -> str:
    """Return a safe display label from a raw cluster topic string.

    Strips URLs (http/https/t.me), @-handles, and email addresses, then
    collapses runs of whitespace to a single space and caps the result to
    TRENDING_LABEL_MAX_LEN characters (with ellipsis if truncated).

    This is the API boundary sanitization required by compliance §7 (AC5):
    ``clusters.topic`` may be raw post text; only a clean display label is
    returned to callers.

    Args:
        raw: The raw ``clusters.topic`` value (centroid label from pipeline).

    Returns:
        A sanitized, human-readable display label ≤ TRENDING_LABEL_MAX_LEN chars.
    """
    cleaned = _RAW_CONTENT_RE.sub("", raw)
    # Collapse multiple whitespace characters (including newlines) to a single space.
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > TRENDING_LABEL_MAX_LEN:
        # Reserve one character for the ellipsis so total len ≤ TRENDING_LABEL_MAX_LEN.
        cleaned = cleaned[: TRENDING_LABEL_MAX_LEN - 1].rstrip() + "…"
    return cleaned


def _get_showcase_user_id(session: Session) -> int | None:
    """Return the showcase user's id, or None if the showcase tenant does not exist."""
    settings = get_settings()
    # Use User.__table__.c.email to work around a mypy false-positive: the email
    # column is declared in SQLAlchemyBaseUserTable (fastapi-users mixin) which
    # mypy cannot resolve to Mapped[str] when accessed as a class attribute
    # comparison — the table column reference always resolves correctly.
    row = session.scalar(select(User).where(User.__table__.c.email == settings.showcase_user_email))
    return row.id if row is not None else None


def _showcase_has_clusters(session: Session, showcase_user_id: int) -> bool:
    """Return True if the showcase user has at least one cluster (warmed)."""
    result = session.scalar(
        select(func.count(Cluster.id)).where(Cluster.user_id == showcase_user_id).limit(1)
    )
    return (result or 0) > 0


def get_trending(
    session: Session,
    *,
    pack_slug: str,
    limit: int,
) -> TrendingResponse:
    """Return top-K showcase viral clusters for the given pack within the 24h window.

    Args:
        session:   Sync SQLAlchemy session.
        pack_slug: Validated pack slug (caller must 404 on unknown slugs before calling).
        limit:     Max number of items to return (≤ settings.trending_top_k_max).

    Returns:
        TrendingResponse with items sorted by viral_score desc + warming_up flag.
    """
    settings = get_settings()
    pack = get_pack(pack_slug)
    # Caller already validated the slug; pack is guaranteed non-None here.
    assert pack is not None, f"pack_slug {pack_slug!r} not in catalog — caller must 404 first"

    # --- Determine showcase user ---
    showcase_id = _get_showcase_user_id(session)
    if showcase_id is None:
        # Showcase tenant not yet bootstrapped → warming up.
        return TrendingResponse(items=[], warming_up=True)

    # --- Check if showcase is warmed (has any clusters at all) ---
    warmed = _showcase_has_clusters(session, showcase_id)
    if not warmed:
        return TrendingResponse(items=[], warming_up=True)

    # --- Query top-K clusters in window ---
    window_start = datetime.now(UTC) - timedelta(seconds=settings.trending_window_seconds)

    stmt = (
        select(
            Cluster.topic,
            Score.viral_score,
            Cluster.first_seen,
        )
        .join(Score, (Score.cluster_id == Cluster.id) & (Score.user_id == Cluster.user_id))
        .where(Cluster.user_id == showcase_id)
        .where(Cluster.topic == pack.topic)
        .where(Cluster.first_seen >= window_start)
        .order_by(Score.viral_score.desc())
        .limit(limit)
    )

    rows = session.execute(stmt).all()

    # Build aggregate-only response items (no raw content, compliance §7).
    # topic is sanitized via _sanitize_topic_label() — clusters.topic may contain
    # raw post text (pipeline cluster.py: post.text[:255]); we strip URLs/@-handles
    # before returning to callers (AC5, compliance §7).
    # channels_count is not persisted separately in the Score model; we default
    # to 1 as a safe placeholder — the scorer writes velocity/engagement/cross_channel
    # but not channels_count directly. To expose a real count, the scorer would need
    # to persist it; for now we expose the cross_channel component (0-1) as a proxy
    # count by using a value of 1 (minimal safe default, honest aggregate).
    # TODO: when scorer persists channels_count per cluster, join it here.
    items = [
        TrendingItem(
            topic=_sanitize_topic_label(row.topic),
            viral_score=row.viral_score,
            channels_count=1,
            first_seen=row.first_seen,
        )
        for row in rows
    ]

    return TrendingResponse(items=items, warming_up=False)


__all__ = ["get_trending"]
