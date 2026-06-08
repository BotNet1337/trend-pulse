"""Celery application wiring (broker + result backend = Redis).

Task args MUST be JSON-serializable (pass ids, not ORM objects) — see CONVENTIONS.
Routing: `run_user_batch` → shared `batch` queue, `score_tick` → static
`score:global`. Per-user `max_instances=1` isolation is enforced by the Redis lock
(pipeline.locks), NOT a per-tenant queue — dynamic per-user queues can't be
consumed by a static worker `-Q` (refinement of ADR-002 §2). The worker subscribes
to `celery,batch,score:global`.
"""

from celery import Celery

from config import get_settings
from pipeline.constants import BATCH_QUEUE, RUN_USER_BATCH_TASK, SCORE_QUEUE, SCORE_TICK_TASK
from scheduler import beat_schedule

_settings = get_settings()

celery_app = Celery(
    "trendpulse",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
    # Tasks live in `pipeline.tasks`; `include` defers their import to worker
    # startup, breaking the `celery_app` <-> `pipeline.tasks` import cycle.
    include=["pipeline.tasks"],
)
celery_app.conf.task_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.result_serializer = "json"
# Ack after the task returns so a worker crash mid-batch redelivers the message
# (the per-user lock + idempotent drain keep redelivery safe — ADR-002).
celery_app.conf.task_acks_late = True
celery_app.conf.beat_schedule = beat_schedule
# Static routes: batches → shared `batch` queue, scorer tick → `score:global`.
celery_app.conf.task_routes = {
    RUN_USER_BATCH_TASK: {"queue": BATCH_QUEUE},
    SCORE_TICK_TASK: {"queue": SCORE_QUEUE},
}


@celery_app.task(name="trendpulse.ping")
def ping() -> str:
    """Skeleton task used as a connectivity smoke check (returns ``"pong"``)."""
    return "pong"
