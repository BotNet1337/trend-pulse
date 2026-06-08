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
    # AC4: batch every 60s, scorer every 300s — sourced from config, asserted here.
    settings = get_settings()
    assert settings.batch_interval_seconds == 60
    assert settings.scorer_interval_seconds == 300


@contextmanager
def _fake_session() -> Iterator[MagicMock]:
    yield MagicMock(name="session")


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
