"""Proof-of-speed case fixation (TASK-045).

``fix_cases(session, settings, now)`` — called from the showcase beat tick
(``showcase/tasks.py::_run_tick_body``) AFTER the posting block.

Algorithm:
1. Resolve showcase-tenant user_id (same as posting tick).
2. SELECT clusters + scores for the showcase tenant within the trending window.
3. For each cluster with viral_score >= settings.showcase_case_min_score:
   a. Build a sanitized snapshot (sanitize_topic_label applied — compliance §7).
   b. INSERT INTO showcase_cases ON CONFLICT DO NOTHING (unique constraint
      ``uq_showcase_cases_title_first_seen``).
4. Flush + commit inside fix_cases.

Isolation:
- Best-effort: called from _run_tick_body under a try/except → fixation failure
  NEVER breaks posting (Invariant from task doc).
- No raw cluster.topic stored — only sanitize_topic_label() output (compliance).

Public helpers (unit-testable without DB):
- ``should_fix_case(cluster, settings)`` — pure threshold check.
- ``build_case_title(raw_topic)`` — sanitize a raw topic string.
- ``build_case_snapshot(cluster)`` — return the snapshot dict.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from textutils import sanitize_topic_label

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# MVP channels_count: the scorer does not persist per-cluster channel counts yet.
# We default to 1 (safe, honest) — a real join would be needed to expose the
# actual source channel count.
# TODO: when scorer persists channels_count per cluster, join and use it here.
_CHANNELS_COUNT_MVP: int = 1


# ---------------------------------------------------------------------------
# Protocol for settings (duck-typed — supports both real Settings and FakeSettings)
# ---------------------------------------------------------------------------


class _CaseSettings(Protocol):
    """Settings fields required by fix_cases."""

    showcase_case_min_score: float
    trending_window_seconds: int
    showcase_user_email: str


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable, no DB dependency)
# ---------------------------------------------------------------------------


def should_fix_case(cluster: Any, *, settings: _CaseSettings) -> bool:
    """Return True if the cluster qualifies for a marketing case snapshot.

    A cluster qualifies when its viral_score is at or above the configured
    ``showcase_case_min_score`` threshold (default 90.0 — higher than the
    autoposting threshold of 85.0, catching only the most exceptional signals).

    Args:
        cluster: Object with a ``.viral_score`` float attribute.
        settings: Settings-like object with ``.showcase_case_min_score``.

    Returns:
        True if cluster.viral_score >= settings.showcase_case_min_score.
    """
    return float(cluster.viral_score) >= settings.showcase_case_min_score


def build_case_title(raw_topic: str) -> str:
    """Return the sanitized display label for a case row.

    Applies ``textutils.sanitize_topic_label()`` to strip URLs, @-handles, and
    email addresses from the raw cluster.topic string.

    COMPLIANCE: this is the ONLY transformation allowed before storing a topic
    string in showcase_cases.  Never store the raw value.

    Args:
        raw_topic: Raw ``cluster.topic`` value (may contain post text, URLs, handles).

    Returns:
        Sanitized label ≤ TOPIC_LABEL_MAX_LEN characters.
    """
    return sanitize_topic_label(raw_topic)


def build_case_snapshot(cluster: Any) -> dict[str, Any]:
    """Return a snapshot dict with all fields required for a showcase_cases insert.

    Fields:
        title:          Sanitized label (sanitize_topic_label applied).
        viral_score:    cluster.viral_score at fixation time.
        first_seen:     cluster.first_seen (detection timestamp).
        channels_count: MVP = 1 (see _CHANNELS_COUNT_MVP docstring).

    Compliance: no raw topic text; only the sanitized title is included.

    Args:
        cluster: Object with .topic (str), .viral_score (float), .first_seen (datetime).

    Returns:
        Dict with keys: title, viral_score, first_seen, channels_count.
    """
    return {
        "title": build_case_title(str(cluster.topic)),
        "viral_score": float(cluster.viral_score),
        "first_seen": cluster.first_seen,
        "channels_count": _CHANNELS_COUNT_MVP,
    }


# ---------------------------------------------------------------------------
# DB-backed fixation
# ---------------------------------------------------------------------------


def fix_cases(
    session: Session,
    *,
    settings: _CaseSettings,
    now: datetime,
) -> None:
    """Fixate qualifying showcase-tenant clusters as marketing case snapshots.

    Selects showcase-tenant clusters with viral_score >= showcase_case_min_score
    within the trending window, and inserts sanitized snapshots into showcase_cases
    using on_conflict_do_nothing for idempotency.

    Called from showcase/tasks.py::_run_tick_body after the posting block, wrapped
    in try/except — fixation MUST NOT break posting on any exception.

    Args:
        session:  SQLAlchemy Session (caller-managed transaction).
        settings: Settings-like object (showcase_case_min_score, trending_window_seconds,
                  showcase_user_email).
        now:      Current UTC datetime (injected for testability).
    """
    from datetime import timedelta

    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from storage.models.clusters import Cluster
    from storage.models.scores import Score
    from storage.models.showcase_cases import ShowcaseCase
    from storage.models.users import User

    # --- Resolve showcase user ---
    showcase_row = session.scalar(
        select(User).where(User.__table__.c.email == settings.showcase_user_email)
    )
    if showcase_row is None:
        logger.warning("fix_cases: showcase user not found — skipping")
        return

    showcase_user_id: int = showcase_row.id

    # --- Query showcase clusters within the trending window ---
    window_start = now - timedelta(seconds=settings.trending_window_seconds)

    stmt = (
        select(
            Cluster.id,
            Cluster.topic,
            Score.viral_score,
            Cluster.first_seen,
        )
        .join(Score, (Score.cluster_id == Cluster.id) & (Score.user_id == Cluster.user_id))
        .where(Cluster.user_id == showcase_user_id)
        .where(Cluster.first_seen >= window_start)
        .where(Score.viral_score >= settings.showcase_case_min_score)
    )

    rows = session.execute(stmt).all()

    if not rows:
        return

    # --- Idempotent insert for each qualifying cluster ---
    for row in rows:
        title = build_case_title(str(row.topic))
        insert_stmt = (
            pg_insert(ShowcaseCase)
            .values(
                title=title,
                viral_score=float(row.viral_score),
                first_seen=row.first_seen,
                channels_count=_CHANNELS_COUNT_MVP,
                mainstream_at=None,
                created_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_showcase_cases_title_first_seen")
        )
        session.execute(insert_stmt)

    session.flush()
    logger.info(
        "fix_cases: processed %d qualifying clusters",
        len(rows),
    )
