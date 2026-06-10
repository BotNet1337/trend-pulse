"""Adaptive threshold beat task (TASK-043).

Two public surfaces:
1. ``compute_threshold_step(current, floor, downvote_share, settings) → float | None``
   Pure function: given current threshold, floor, and downvote share, returns the
   new threshold or None (no-op).  [floor, floor+range] invariant is enforced here.

2. ``resolve_floor(current_threshold, threshold_floor) → float``
   Pure function: if floor is None (first adapt tick), snapshots to current_threshold.

3. ``apply_threshold_change(session, watchlist, new_threshold, downvote_share, reason)``
   Mutates the watchlist row in-session and emits log_event("threshold_adapted").

4. ``adapt_thresholds()``
   Celery beat task body: iterates users with ≥K ratings in the 7d window, computes
   per-user downvote_share, and applies the step to ALL that user's watchlists
   (Discussion decision: per-watchlist apply, per-user share — MVP simplification).

   Registered as a Celery task via ``@celery_app.task(name=ADAPT_THRESHOLDS_TASK)``.
   Uses lazy imports to avoid import cycles (same pattern as observability/tasks.py).

Import note: this module imports ``celery_app`` (task registration) but NOT
``alerts.tasks`` or ``pipeline.tasks``.  ``compute_threshold_step`` and
``resolve_floor`` do NOT import ``celery_app`` — safe to import from tests.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from config import get_settings
from observability.logging import log_event
from scorer.constants import ADAPT_THRESHOLDS_TASK
from storage.database import get_session
from storage.models.alert_feedback import VERDICT_DOWN
from storage.models.watchlists import Watchlist

if TYPE_CHECKING:
    from config import Settings

logger = logging.getLogger(__name__)

# Downvote-share query window — matches precision_window_seconds (7 days).
# Named constant so the window is explicit and cannot drift from the precision metric.
_ADAPT_WINDOW_SECONDS: int = 604_800  # 7 days

# Column aliases for the downvote-share query (same DRY pattern as signal_latency.py).
_COL_TOTAL = "total"
_COL_DOWN = "down"


# ---------------------------------------------------------------------------
# Pure functions (no I/O — safe to test without DB)
# ---------------------------------------------------------------------------


def resolve_floor(current_threshold: float, threshold_floor: float | None) -> float:
    """Resolve the effective floor for a watchlist.

    If ``threshold_floor`` is NULL (not yet snapshotted), the floor snapshots to
    the current threshold value (Discussion: floor = value the user last set manually;
    the first adapt tick uses current threshold as the user's intent baseline).

    Args:
        current_threshold: The watchlist's current threshold value.
        threshold_floor: The persisted floor (may be None for pre-TASK-043 rows).

    Returns:
        The effective floor: either the persisted value or current_threshold.
    """
    if threshold_floor is None:
        return current_threshold
    return threshold_floor


def compute_threshold_step(
    current_threshold: float,
    floor: float,
    downvote_share: float,
    settings: Settings,
) -> float | None:
    """Compute the new threshold after one adapt tick (pure function).

    Rules (all from Settings — no magic literals):
    - ``downvote_share > up_share`` → threshold += step (cap at floor + range).
    - ``downvote_share < down_share`` → threshold -= step (floor at floor).
    - Otherwise (dead zone) → no-op (return None).
    - If the computed value equals current (already at boundary) → return None.

    Args:
        current_threshold: Current watchlist threshold.
        floor: Effective floor (resolved via ``resolve_floor``).
        downvote_share: Fraction of 👎 among all rated alerts in the window.
        settings: Application settings (reads adapt_{step,range,up_share,down_share}).

    Returns:
        New threshold value, or None if no change is warranted.
    """
    ceiling = floor + settings.threshold_adapt_range

    if downvote_share > settings.threshold_adapt_up_share:
        # Step up — cap at ceiling.
        new = min(current_threshold + settings.threshold_adapt_step, ceiling)
    elif downvote_share < settings.threshold_adapt_down_share:
        # Step down — floor at floor.
        new = max(current_threshold - settings.threshold_adapt_step, floor)
    else:
        # Dead zone — no change.
        return None

    # If already at the boundary, no movement needed.
    if abs(new - current_threshold) < 1e-9:
        return None

    return new


# ---------------------------------------------------------------------------
# Session-level helpers
# ---------------------------------------------------------------------------


def apply_threshold_change(
    session: Session,
    watchlist: Watchlist,
    new_threshold: float,
    downvote_share: float,
    reason: str,
) -> None:
    """Update a watchlist's threshold in-session and emit a log_event.

    Invariants enforced by ``compute_threshold_step`` (caller) — this function
    trusts the new_threshold is within [floor, floor+range].  Emits
    ``log_event("threshold_adapted", ...)`` for every change (explainability).

    Args:
        session: Open SQLAlchemy Session (caller manages lifecycle).
        watchlist: The Watchlist ORM row to update.
        new_threshold: Pre-validated new threshold value.
        downvote_share: The downvote share that triggered the change (for logs).
        reason: "up" or "down" — direction of the change (for logs).
    """
    old_threshold = watchlist.threshold
    watchlist.threshold = new_threshold
    log_event(
        "threshold_adapted",
        watchlist_id=watchlist.id,
        user_id=watchlist.user_id,
        old=old_threshold,
        new=new_threshold,
        downvote_share=downvote_share,
        reason=reason,
    )


def _query_downvote_share(
    session: Session,
    *,
    user_id: int,
    window_seconds: int,
    min_ratings: int,
) -> float | None:
    """Compute per-user downvote share in the adapt window.

    Returns the fraction of 👎 votes among all rated alerts in the sliding window,
    or None if the user has fewer than min_ratings rated alerts (AC3 guard).

    SQL:
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN af.verdict = :down THEN 1 ELSE 0 END) AS down
        FROM alert_feedback AS af
        WHERE af.user_id = :user_id
          AND af.updated_at >= NOW() - make_interval(secs => :window_seconds)

    Uses bind params for all values (f-string only for constant column aliases —
    same pattern as emit_alert_precision in signal_latency.py).
    """
    # Column aliases are constant strings, not user input — safe to format.
    sql = text(
        f"""
        SELECT
            COUNT(*) AS {_COL_TOTAL},
            CAST(SUM(CASE WHEN af.verdict = :down THEN 1 ELSE 0 END) AS BIGINT) AS {_COL_DOWN}
        FROM alert_feedback AS af
        WHERE af.user_id = :user_id
          AND af.updated_at >= NOW() - make_interval(secs => :window_seconds)
        """
    )

    row = session.execute(
        sql,
        {
            "user_id": user_id,
            "down": VERDICT_DOWN,
            "window_seconds": float(window_seconds),
        },
    ).one()

    mapping = row._mapping
    total: int = int(mapping[_COL_TOTAL]) if mapping[_COL_TOTAL] is not None else 0
    down: int = int(mapping[_COL_DOWN]) if mapping[_COL_DOWN] is not None else 0

    if total < min_ratings:
        return None

    return down / total


def _adapt_user(session: Session, *, user_id: int, settings: Settings) -> int:
    """Apply adapt-tick for one user; return number of watchlists changed."""
    # Compute per-user downvote share over the adapt window.
    downvote_share = _query_downvote_share(
        session,
        user_id=user_id,
        window_seconds=_ADAPT_WINDOW_SECONDS,
        min_ratings=settings.threshold_adapt_min_ratings,
    )
    if downvote_share is None:
        # AC3: < K ratings → no-op.
        return 0

    # Apply to ALL the user's watchlists (Discussion: per-user share, per-watchlist floor).
    watchlists = list(session.scalars(select(Watchlist).where(Watchlist.user_id == user_id)).all())
    changed = 0
    for wl in watchlists:
        # AC6: snapshot floor if NULL.
        effective_floor = resolve_floor(wl.threshold, wl.threshold_floor)
        if wl.threshold_floor is None:
            # Persist the snapshot.
            wl.threshold_floor = effective_floor

        new_threshold = compute_threshold_step(
            current_threshold=wl.threshold,
            floor=effective_floor,
            downvote_share=downvote_share,
            settings=settings,
        )
        if new_threshold is None:
            continue

        reason = "up" if new_threshold > wl.threshold else "down"
        apply_threshold_change(
            session,
            watchlist=wl,
            new_threshold=new_threshold,
            downvote_share=downvote_share,
            reason=reason,
        )
        changed += 1

    return changed


def _user_ids_with_ratings(session: Session, *, window_seconds: int) -> list[int]:
    """Return distinct user_ids that have at least one feedback row in the window.

    Uses raw SQL with make_interval for the sliding window (same pattern as
    emit_alert_precision in signal_latency.py — bind params for values only).
    """
    sql = text(
        """
        SELECT DISTINCT af.user_id
        FROM alert_feedback AS af
        WHERE af.updated_at >= NOW() - make_interval(secs => :window_seconds)
        """
    )
    rows = session.execute(sql, {"window_seconds": float(window_seconds)}).all()
    return [int(row[0]) for row in rows]


# ---------------------------------------------------------------------------
# Beat task
# ---------------------------------------------------------------------------


def adapt_thresholds() -> int:
    """Adapt-thresholds beat-task body (TASK-043).

    For each user with ≥K feedback ratings in the 7d window, computes downvote_share
    and applies the threshold step to all their watchlists.  Returns total watchlists
    changed across all users this tick.

    Each user's watchlists are processed in their own DB session (same pattern as
    ``score_recent_clusters``) so a failure for one user does not abort others.
    Best-effort: logs warnings on exception per user (same pattern as
    observability/tasks.py).
    """
    settings = get_settings()
    total_changed = 0
    user_count = 0

    with get_session() as session:
        user_ids = _user_ids_with_ratings(session, window_seconds=_ADAPT_WINDOW_SECONDS)

    for user_id in user_ids:
        user_count += 1
        try:
            with get_session() as session:
                changed = _adapt_user(session, user_id=user_id, settings=settings)
                total_changed += changed
        except Exception as exc:
            logger.warning(
                "adapt_thresholds: failed for user_id=%s",
                user_id,
                extra={"exc_type": type(exc).__name__},
            )

    logger.info(
        "adapt_thresholds watchlists_changed=%d users=%d",
        total_changed,
        user_count,
    )
    return total_changed


# ---------------------------------------------------------------------------
# Celery task registration (lazy imports — no cycle)
# ---------------------------------------------------------------------------

from celery_app import celery_app  # noqa: E402 — import after module-level defs


@celery_app.task(name=ADAPT_THRESHOLDS_TASK)
def adapt_thresholds_task() -> None:
    """Beat task: adapt per-user watchlist thresholds based on 👎 share.

    Best-effort: failures per user are logged as warnings; the task does not
    propagate exceptions to Celery (no retry — the next tick will catch up).

    Scheduled via ``scheduler.beat_schedule`` at
    ``settings.threshold_adapt_interval_seconds`` (default 21600s = 6h).
    """
    try:
        adapt_thresholds()
    except Exception as exc:
        logger.warning(
            "adapt_thresholds_task: unexpected error",
            extra={"exc_type": type(exc).__name__},
        )
