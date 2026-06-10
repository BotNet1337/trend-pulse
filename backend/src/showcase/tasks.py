"""Showcase autopost beat task (TASK-044).

`showcase_autopost_tick()` — Celery beat task registered as
``showcase.tasks.showcase_autopost_tick`` (name = SHOWCASE_AUTOPOST_TASK in
showcase/constants.py; included in celery_app.include so the decorator is
evaluated at worker startup, breaking the celery_app ← showcase cycle).

Algorithm per tick:
1. Check creds (token + chat_id): empty → warn-once + return (AC4).
2. Check public_base_url: empty while creds present → warn-once + return (AC4/CTA).
3. SELECT showcase-tenant clusters + scores in the 24h window (all candidates).
4. SELECT posted_cluster_ids from showcase_posts WHERE status=posted ONLY
   (pending rows are excluded so a failed-send cluster can be retried — AC3).
5. COUNT posts_today = posted rows today (UTC day, status=posted only).
   Pending rows do NOT consume the daily cap (AC5).
6. Call pick_best_candidate() → best cluster (pure filter, AC1/AC5).
7. None → return (nothing to post this tick).
8. INSERT showcase_posts(cluster_id, status=pending, created_at=now) with
   on_conflict_do_nothing (INSERT-first idempotency — race-safe, AC3).
   Committed in its own transaction BEFORE send so pending is durable.
9. Re-fetch the row inside a new session; if status=posted (another worker beat
   us) → return.
10. Build text, send via sender.send_showcase_post().
11. Success → UPDATE status=posted, posted_at=now (committed).
    Failure → leave pending; next tick retries (AC3).

Error handling:
- Best-effort try/except around the whole body: beat MUST NOT crash (AC4/Invariant).
- DB exceptions are logged and suppressed — the beat framework must continue.

Import note: imports celery_app at module level (required for @celery_app.task).
All other heavy imports (sqlalchemy, models) are done inside the function body
to isolate the import-time side effects and keep tests fast.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, NamedTuple

from celery_app import celery_app
from observability.logging import log_event
from showcase.constants import SHOWCASE_AUTOPOST_TASK
from showcase.sender import send_showcase_post

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Warn-once flags for missing/invalid configuration (AC4 — same pattern as TASK-035).
_WARNED_NO_CREDS: bool = False
_WARNED_NO_PUBLIC_BASE_URL: bool = False


# ---------------------------------------------------------------------------
# Typed row proxy — replaces the inner class that carried # type: ignore
# ---------------------------------------------------------------------------


class _ClusterRow(NamedTuple):
    """Typed projection of the ORM row returned by the showcase cluster query."""

    id: int
    topic: str
    viral_score: float
    first_seen: datetime


# ---------------------------------------------------------------------------
# Core tick body (extracted for testability — session is injected by caller)
# ---------------------------------------------------------------------------


def _run_tick_body(session: Session) -> None:
    """Core tick logic, extracted for testability (session is injected by caller).

    Separated from the Celery task decorator so unit tests can call this directly
    with a mock/real session without going through Celery plumbing.

    Invariant (TASK-045): fix_cases() runs unconditionally — fixation is independent
    of posting credentials.  The posting-creds guard only controls the posting path.
    """
    from sqlalchemy import func, select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from config import get_settings
    from showcase.formatting import build_showcase_post, sanitize_topic
    from showcase.selection import pick_best_candidate
    from storage.models.clusters import Cluster
    from storage.models.scores import Score
    from storage.models.showcase_posts import STATUS_PENDING, STATUS_POSTED, ShowcasePost
    from storage.models.users import User

    settings = get_settings()
    global _WARNED_NO_CREDS, _WARNED_NO_PUBLIC_BASE_URL

    now = datetime.now(UTC)

    # --- Fixate qualifying clusters as proof-of-speed cases (TASK-045) ---
    # Runs unconditionally — fixation is INDEPENDENT of posting credentials.
    # Best-effort: any exception is logged and suppressed so the beat loop always
    # continues and posting is never blocked (Invariant).
    try:
        from showcase.cases import fix_cases

        fix_cases(session, settings=settings, now=now)
        session.commit()
    except Exception as cases_exc:
        logger.warning(
            "fix_cases error — suppressed (fixation must not break posting)",
            extra={"exc_type": type(cases_exc).__name__},
        )

    # AC4: check creds; no-op + warn-once if missing.
    # Posting guard is AFTER fix_cases so fixation always happens regardless of creds.
    if not settings.showcase_bot_token or not settings.showcase_channel_chat_id:
        if not _WARNED_NO_CREDS:
            _WARNED_NO_CREDS = True
            logger.warning(
                "showcase_autopost disabled — missing showcase_bot_token or "
                "showcase_channel_chat_id (set in sensitive.env / vault to enable)"
            )
        return

    # Fix #5: CTA requires public_base_url — no fallback to telegram_api_base_url.
    # A CTA-less showcase post defeats the feature (the whole point is the link).
    if not settings.public_base_url:
        if not _WARNED_NO_PUBLIC_BASE_URL:
            _WARNED_NO_PUBLIC_BASE_URL = True
            log_event("showcase_skip", reason="no_public_base_url")
            logger.warning(
                "showcase_autopost disabled — public_base_url is empty; "
                "set PUBLIC_BASE_URL in deploy.env to enable CTA links"
            )
        return

    # --- Resolve showcase user ---
    showcase_row = session.scalar(
        select(User).where(User.__table__.c.email == settings.showcase_user_email)
    )
    if showcase_row is None:
        log_event("showcase_autopost_skip", reason="no_showcase_user")
        return
    showcase_user_id: int = showcase_row.id

    # --- Query showcase clusters within 24h window ---
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
        .order_by(Score.viral_score.desc())
    )
    raw_rows = session.execute(stmt).all()

    # Build typed NamedTuple projections — no type: ignore needed.
    clusters: list[_ClusterRow] = [
        _ClusterRow(
            id=int(r.id),
            topic=str(r.topic),
            viral_score=float(r.viral_score),
            first_seen=r.first_seen,
        )
        for r in raw_rows
    ]

    # --- Fix #1: dedup set = POSTED rows ONLY (exclude pending so retry works) ---
    # A pending row means send failed — the cluster MUST be re-eligible next tick.
    # Including pending rows in the exclusion set permanently blocks re-selection,
    # breaking AC3 (retry semantics).
    posted_ids_rows = session.execute(
        select(ShowcasePost.cluster_id).where(ShowcasePost.status == STATUS_POSTED)
    ).all()
    posted_cluster_ids: set[int] = {r.cluster_id for r in posted_ids_rows}

    # --- Count posts today (UTC day) — POSTED rows only; pending must not eat cap ---
    # Fix #1 (cap): counting pending rows toward the cap means a stuck pending
    # blocks ALL further posting for the UTC day.  Only POSTED rows are real posts.
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    posts_today_count: int = (
        session.scalar(
            select(func.count(ShowcasePost.id)).where(
                ShowcasePost.status == STATUS_POSTED,
                ShowcasePost.posted_at >= today_start,
            )
        )
        or 0
    )

    # --- Pure selection ---
    best = pick_best_candidate(
        clusters=clusters,
        posted_cluster_ids=posted_cluster_ids,
        posts_today=posts_today_count,
        now=now,
        settings=settings,
    )

    if best is None:
        log_event("showcase_autopost_skip", reason="no_candidate")
        return

    # --- Fix #2: durable pending — commit INSERT before send (two-phase approach) ---
    # Pending must be committed to DB BEFORE the send so that:
    # (a) If the process crashes between commit and send, the next tick sees the
    #     pending row — but since we now exclude pending from the dedup set (Fix #1),
    #     the cluster is re-eligible and gets re-selected; the INSERT no-ops via
    #     on_conflict_do_nothing and we proceed to send again.  This gives us the
    #     retry semantics required by AC3.
    # (b) If another beat instance races us, the UNIQUE constraint prevents double-post.
    #
    # We execute the INSERT and commit via the caller-supplied session (matching
    # get_session usage patterns: session.flush → session.commit commits the pending
    # row as a standalone transaction; we then re-use the same session for the rest
    # of the tick — SQLAlchemy re-opens the transaction automatically on next access).
    insert_stmt = (
        pg_insert(ShowcasePost)
        .values(
            cluster_id=best.id,
            status=STATUS_PENDING,
            created_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_showcase_posts_cluster_id")
    )
    session.execute(insert_stmt)
    session.flush()
    session.commit()  # Durable pending — survives crash before send.

    # Re-fetch the row to check current status (another worker may have posted it
    # between our INSERT and now — the commit makes their changes visible).
    sp_row = session.scalar(select(ShowcasePost).where(ShowcasePost.cluster_id == best.id))
    if sp_row is None:
        # Should not happen (we just inserted/saw it), but defensive guard.
        log_event("showcase_autopost_skip", reason="row_missing_after_insert")
        return

    if sp_row.status == STATUS_POSTED:
        # Another worker already delivered this cluster.
        log_event("showcase_autopost_skip", reason="already_posted", cluster_id=best.id)
        return

    # --- Build and send ---
    sanitized_topic = sanitize_topic(best.topic)
    text = build_showcase_post(
        topic=sanitized_topic,
        score=best.viral_score,
        first_seen=best.first_seen,
        public_base_url=settings.public_base_url,
    )

    sent = send_showcase_post(
        token=settings.showcase_bot_token,
        chat_id=settings.showcase_channel_chat_id,
        text=text,
        base_url=settings.telegram_api_base_url,
        timeout=settings.alert_http_timeout_seconds,
    )

    if sent:
        sp_row.status = STATUS_POSTED
        sp_row.posted_at = datetime.now(UTC)
        session.flush()
        log_event(
            "showcase_post_delivered",
            cluster_id=best.id,
            score=best.viral_score,
        )
    else:
        # Leave pending — next tick retries (AC3).
        log_event(
            "showcase_post_pending_retry",
            cluster_id=best.id,
        )


@celery_app.task(name=SHOWCASE_AUTOPOST_TASK)
def showcase_autopost_tick() -> None:
    """Beat task: select best showcase cluster and post to TG channel.

    Best-effort: catches all exceptions so the beat loop never crashes (AC4 /
    Invariant). DB exceptions are logged (not re-raised).
    """
    from storage.database import get_session

    try:
        with get_session() as session:
            _run_tick_body(session)
    except Exception as exc:
        # Broad safety net: beat must never crash.
        logger.warning(
            "showcase_autopost_tick unexpected error — suppressed",
            extra={"exc_type": type(exc).__name__},
        )
