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


# --- TASK-099: Celery runtime memory/hang guards ---


def test_worker_child_recycling_from_settings() -> None:
    """worker_max_tasks_per_child bounds torch/native creep (CRITICAL audit finding)."""
    from config import get_settings

    s = get_settings()
    assert celery_app.conf.worker_max_tasks_per_child == s.celery_worker_max_tasks_per_child
    assert s.celery_worker_max_tasks_per_child == 250


def test_worker_concurrency_pinned_from_settings() -> None:
    """Concurrency pinned (not host os.cpu_count()) so a many-core host can't fork
    many model-loading children → OOM."""
    from config import get_settings

    s = get_settings()
    assert celery_app.conf.worker_concurrency == s.celery_worker_concurrency
    assert s.celery_worker_concurrency == 2


def test_task_time_limits_from_settings_and_ordered() -> None:
    """A stuck task (embed / pgvector NN) must not pin a slot forever (CRITICAL)."""
    from config import get_settings

    s = get_settings()
    assert celery_app.conf.task_soft_time_limit == s.celery_task_soft_time_limit_seconds
    assert celery_app.conf.task_time_limit == s.celery_task_time_limit_seconds
    assert s.celery_task_soft_time_limit_seconds < s.celery_task_time_limit_seconds


def test_result_expires_bounds_redis_result_keys() -> None:
    """Short result TTL protects the 224mb noeviction Redis from result-meta churn."""
    from config import get_settings

    s = get_settings()
    assert celery_app.conf.result_expires == s.celery_result_expires_seconds
    assert s.celery_result_expires_seconds == 3600


def test_task_time_limit_validator_rejects_soft_ge_hard() -> None:
    """Runtime check: soft must be strictly below hard, else SoftTimeLimitExceeded never
    fires before the hard SIGKILL."""
    import pytest
    from pydantic import ValidationError

    from config import Settings

    with pytest.raises(ValidationError):
        Settings(
            celery_task_soft_time_limit_seconds=1200,
            celery_task_time_limit_seconds=1200,
        )
    with pytest.raises(ValidationError):
        Settings(
            celery_task_soft_time_limit_seconds=1300,
            celery_task_time_limit_seconds=1200,
        )


def test_batch_lock_ttl_covers_task_hard_limit() -> None:
    """Review HIGH: the per-user batch lock must outlive a hard-killed task so a
    redelivery can't run the same user concurrently."""
    from config import get_settings

    s = get_settings()
    assert s.batch_lock_ttl_seconds >= s.celery_task_time_limit_seconds
    assert s.batch_lock_ttl_seconds == 1260


def test_lock_ttl_validator_rejects_ttl_below_hard_limit() -> None:
    """Runtime check: a batch lock TTL shorter than the hard limit is rejected."""
    import pytest
    from pydantic import ValidationError

    from config import Settings

    with pytest.raises(ValidationError):
        Settings(batch_lock_ttl_seconds=600, celery_task_time_limit_seconds=1200)
