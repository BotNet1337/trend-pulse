"""Celery task seams for the per-user pipeline + scorer (ADR-002, task-006).

These are *contracts*, not business logic: real pipeline processing arrives in
task-007 (`run_user_batch` body) and the scorer in task-008 (`score_tick`). Every
task takes only JSON-serializable ids (CONVENTIONS) — never ORM objects — and the
per-user batch is serialized by the Redis lock from `pipeline.locks`
(`max_instances=1` semantics).

Task registration: `celery_app` includes this module, so importing the package
binds these tasks to the app. We import `celery_app` lazily inside a late binding
to avoid a circular import (`celery_app` -> `scheduler`; tasks reference the app).
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from celery_app import celery_app
from pipeline.batch_processor import process_user_batch
from pipeline.constants import (
    BATCH_QUEUE,
    ENQUEUE_BATCHES_TASK,
    RUN_USER_BATCH_TASK,
    SCORE_TICK_TASK,
)
from pipeline.locks import user_batch_lock
from storage.database import get_session
from storage.models.watchlists import Watchlist
from storage.redis_client import get_redis_client

logger = logging.getLogger(__name__)


def list_active_user_ids(session: Session) -> list[int]:
    """Return distinct ids of users with at least one watchlist (read-only).

    "Active" == owns a watchlist (ADR-002: only such users have sources to batch).
    A pure read over `watchlists.user_id` — no model/migration change.
    """
    stmt = select(Watchlist.user_id).distinct()
    return list(session.scalars(stmt).all())


@celery_app.task(name=RUN_USER_BATCH_TASK)
def run_user_batch(user_id: int) -> None:
    """Run one user's batch under the per-user lock (`max_instances=1`).

    Acquires the user's batch lock; if it is already held, the batch is a clean
    no-op ("skipped: locked", AC2) so a double-enqueue from beat cannot run two
    batches for the same user in parallel. When acquired it runs the pipeline body
    (`process_user_batch`: drain → dedup → normalize → embed → cluster → persist,
    task-007) and always releases the lock on exit.
    """
    redis = get_redis_client()
    with user_batch_lock(redis, user_id) as acquired:
        if not acquired:
            logger.info("run_user_batch skipped: locked user_id=%s", user_id)
            return
        logger.info("run_user_batch start user_id=%s", user_id)
        process_user_batch(user_id)


@celery_app.task(name=ENQUEUE_BATCHES_TASK)
def enqueue_active_user_batches() -> None:
    """Beat dispatcher: enqueue exactly one batch per active user (AC3).

    Reads the active-user ids via the storage session and puts one
    `run_user_batch` task per id onto the shared `batch` queue (per-user isolation
    is the Redis lock's job, not the queue). Args are JSON-serializable ids only
    (CONVENTIONS). Zero active users → zero tasks.
    """
    with get_session() as session:
        user_ids = list_active_user_ids(session)
    for user_id in user_ids:
        run_user_batch.apply_async(args=(user_id,), queue=BATCH_QUEUE)
    logger.info("enqueue_active_user_batches dispatched=%d", len(user_ids))


@celery_app.task(name=SCORE_TICK_TASK)
def score_tick() -> None:
    """Scorer tick seam (task-008). No-op now; scoring formulas land later."""
    logger.info("score_tick (seam, no-op)")
