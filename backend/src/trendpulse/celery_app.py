"""Celery application wiring (broker + result backend = Redis).

Task args MUST be JSON-serializable (pass ids, not ORM objects) — see CONVENTIONS.
"""

from celery import Celery

from trendpulse.config import get_settings
from trendpulse.scheduler import beat_schedule

_settings = get_settings()

celery_app = Celery(
    "trendpulse",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
)
celery_app.conf.task_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.result_serializer = "json"
celery_app.conf.beat_schedule = beat_schedule


@celery_app.task(name="trendpulse.ping")
def ping() -> str:
    """Skeleton task used as a connectivity smoke check (returns ``"pong"``)."""
    return "pong"
