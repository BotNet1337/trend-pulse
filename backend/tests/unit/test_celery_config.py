"""AC5 + AC6 — Celery app config: JSON serialization, routing, registered tasks.

Pure config assertions; no broker connection is opened.
"""

from celery_app import celery_app
from pipeline.constants import (
    ENQUEUE_BATCHES_TASK,
    RUN_USER_BATCH_TASK,
    SCORE_QUEUE,
    SCORE_TICK_TASK,
)


def test_json_serialization_settings() -> None:
    conf = celery_app.conf
    assert conf.task_serializer == "json"
    assert conf.result_serializer == "json"
    assert conf.accept_content == ["json"]


def test_acks_late_enabled() -> None:
    assert celery_app.conf.task_acks_late is True


def test_broker_and_backend_are_redis() -> None:
    assert str(celery_app.conf.broker_url).startswith("redis://")
    assert str(celery_app.conf.result_backend).startswith("redis://")


def test_score_tick_routed_to_static_queue() -> None:
    routes = celery_app.conf.task_routes
    assert routes[SCORE_TICK_TASK] == {"queue": SCORE_QUEUE}


def test_pipeline_tasks_are_registered() -> None:
    # `include=["pipeline.tasks"]` + importing the module binds the tasks.
    import pipeline.tasks  # noqa: F401  (import for registration side effect)

    registered = set(celery_app.tasks.keys())
    assert RUN_USER_BATCH_TASK in registered
    assert ENQUEUE_BATCHES_TASK in registered
    assert SCORE_TICK_TASK in registered


def test_ping_task_still_registered() -> None:
    # task-001 AC6 must not break.
    assert "trendpulse.ping" in celery_app.tasks
