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
from observability.celery_logging import register_celery_logging
from observability.logging import configure_logging
from observability.sentry import init_sentry
from pipeline.constants import BATCH_QUEUE, RUN_USER_BATCH_TASK, SCORE_QUEUE, SCORE_TICK_TASK
from scheduler import beat_schedule

_settings = get_settings()

celery_app = Celery(
    "trendpulse",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
    # Tasks live in `pipeline.tasks` + `alerts.tasks` + `compliance.tasks`;
    # `include` defers their import to worker startup, breaking the `celery_app`
    # <-> task-module import cycle. `alerts.tasks.dispatch_alert` (task-009) and
    # `compliance.tasks.purge_expired_raw_content` (task-011) are unrouted → they
    # land on the default `celery` queue the worker already consumes (no compose
    # change).
    include=[
        "pipeline.tasks",
        "alerts.tasks",
        "compliance.tasks",
        "billing.tasks",
        "observability.tasks",
        "scorer.adaptation",
    ],
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

# JSON logging for the worker/beat process (TASK-024): without this the worker
# uses Celery's default text handler, so `log_event` lines are not JSON and the
# RequestIdFilter (which injects `request_id` into every record) is never attached
# — the cross-process trace id would be invisible in worker logs. Mirrors the
# `api.main` call so api + worker emit the same JSON shape with `request_id`.
configure_logging()
# Structured, aggregate-only task lifecycle logging (task-011): connect the
# task_prerun/postrun signals so worker logs carry task name/duration/state —
# never args/return/raw content (overview §7).
register_celery_logging()
# Sentry error-tracking (TASK-024): no-op when SENTRY_DSN is empty (dev default).
init_sentry("worker")


@celery_app.task(name="trendpulse.ping")
def ping() -> str:
    """Skeleton task used as a connectivity smoke check (returns ``"pong"``)."""
    return "pong"
