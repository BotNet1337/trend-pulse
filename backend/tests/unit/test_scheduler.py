"""AC3 + AC4 — beat schedule structure and the active-user batch dispatcher.

Infra-free: the DB session is mocked and `run_user_batch.apply_async` is patched,
so no Postgres/Redis is touched (stays clean under `make ci-fast`).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from config import get_settings
from pipeline.constants import ENQUEUE_BATCHES_TASK, SCORE_TICK_TASK
from scheduler import beat_schedule


def test_beat_schedule_has_both_entries_with_config_intervals() -> None:
    settings = get_settings()
    batch_entry = beat_schedule["enqueue-active-user-batches"]
    score_entry = beat_schedule["score-tick"]

    assert batch_entry["task"] == ENQUEUE_BATCHES_TASK
    assert batch_entry["schedule"] == float(settings.batch_interval_seconds)
    assert score_entry["task"] == SCORE_TICK_TASK
    assert score_entry["schedule"] == float(settings.scorer_interval_seconds)


def test_intervals_match_documented_defaults() -> None:
    # AC4: batch every 60s, scorer every 60s (TASK-127: lowered 300->60 for latency).
    # Invariant collect <= batch <= scorer keeps the scorer from out-pacing ingest.
    settings = get_settings()
    assert settings.batch_interval_seconds == 60
    assert settings.scorer_interval_seconds == 60
    assert settings.collect_interval_seconds <= settings.batch_interval_seconds
    assert settings.batch_interval_seconds <= settings.scorer_interval_seconds


@contextmanager
def _fake_session() -> Iterator[MagicMock]:
    yield MagicMock(name="session")


def test_lifecycle_emails_tick_entry_with_config_interval() -> None:
    """TASK-069: daily lifecycle-emails tick is scheduled from settings."""
    from notifications.constants import SEND_LIFECYCLE_EMAILS_TASK

    settings = get_settings()
    entry = beat_schedule["lifecycle-emails-tick"]

    assert entry["task"] == SEND_LIFECYCLE_EMAILS_TASK
    assert entry["schedule"] == float(settings.lifecycle_email_interval_seconds)
    # Documented default: once per day (86400s), same cadence as renewal check.
    assert settings.lifecycle_email_interval_seconds == 86_400


def test_dispatcher_enqueues_one_batch_per_active_user() -> None:
    from pipeline import tasks

    active_ids = [1, 2, 5]
    with (
        patch.object(tasks, "get_session", _fake_session),
        patch.object(tasks, "list_active_user_ids", return_value=active_ids),
        patch.object(tasks.run_user_batch, "apply_async") as apply_async,
    ):
        tasks.enqueue_active_user_batches()

    from pipeline.constants import BATCH_QUEUE

    assert apply_async.call_count == len(active_ids)
    for call, uid in zip(apply_async.call_args_list, active_ids, strict=True):
        assert call.kwargs["args"] == (uid,)
        # One task per active user onto the shared batch queue (per-user isolation
        # is the Redis lock's job, not a per-tenant queue — refinement of ADR-002).
        assert call.kwargs["queue"] == BATCH_QUEUE
        # JSON-serializable args only: a plain int (CONVENTIONS / AC3).
        assert isinstance(call.kwargs["args"][0], int)


def test_dispatcher_no_active_users_enqueues_nothing() -> None:
    from pipeline import tasks

    with (
        patch.object(tasks, "get_session", _fake_session),
        patch.object(tasks, "list_active_user_ids", return_value=[]),
        patch.object(tasks.run_user_batch, "apply_async") as apply_async,
    ):
        tasks.enqueue_active_user_batches()

    apply_async.assert_not_called()


# --- TASK-098: beat heartbeat scheduler (hung-beat liveness signal) ---


def test_heartbeat_scheduler_stamps_key_with_ttl() -> None:
    """tick() stamps a TTL'd Redis heartbeat, then delegates to super().tick()."""
    import scheduler as sched

    fake_redis = MagicMock(name="redis")
    with (
        patch.object(sched, "get_redis_client", return_value=fake_redis),
        patch.object(sched.PersistentScheduler, "__init__", return_value=None),
        patch.object(sched.PersistentScheduler, "tick", return_value=42.0) as super_tick,
    ):
        scheduler = sched.HeartbeatScheduler()
        result = scheduler.tick()

    assert result == 42.0  # delegates to super, returns "seconds to next tick"
    super_tick.assert_called_once()
    fake_redis.set.assert_called_once()
    call = fake_redis.set.call_args
    assert call.args[0] == sched.BEAT_HEARTBEAT_KEY
    assert call.kwargs.get("ex") == get_settings().beat_heartbeat_ttl_seconds


def test_heartbeat_scheduler_tolerates_redis_error() -> None:
    """A Redis blip in the heartbeat write must NOT crash the scheduler loop."""
    from redis import RedisError

    import scheduler as sched

    fake_redis = MagicMock(name="redis")
    fake_redis.set.side_effect = RedisError("boom")
    with (
        patch.object(sched, "get_redis_client", return_value=fake_redis),
        patch.object(sched.PersistentScheduler, "__init__", return_value=None),
        patch.object(sched.PersistentScheduler, "tick", return_value=7.0) as super_tick,
    ):
        scheduler = sched.HeartbeatScheduler()
        result = scheduler.tick()  # must not raise

    assert result == 7.0
    super_tick.assert_called_once()


def test_beat_heartbeat_ttl_exceeds_beat_max_interval() -> None:
    """TTL must exceed Celery beat's 300s max_interval so a healthy beat never lets
    the heartbeat key expire (else the healthcheck would flap)."""
    settings = get_settings()
    assert settings.beat_heartbeat_ttl_seconds == 600
    assert settings.beat_heartbeat_ttl_seconds > 300
