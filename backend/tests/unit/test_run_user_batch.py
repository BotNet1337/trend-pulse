"""AC2 — a user's batch does not run while the per-user lock is held.

Infra-free: the Redis client and the lock context manager are patched, so no live
Redis is needed. Celery tasks are plain callables, so we invoke the task body
synchronously.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import fakeredis
import pytest

from pipeline import tasks
from pipeline.locks import acquire_user_batch_lock


def _patch_redis() -> object:
    return patch.object(tasks, "get_redis_client", return_value=MagicMock())


def test_run_user_batch_skips_when_locked(caplog: pytest.LogCaptureFixture) -> None:
    @contextmanager
    def _locked(*_args: object, **_kwargs: object) -> Iterator[bool]:
        yield False  # lock already held by another holder

    with (
        _patch_redis(),
        patch.object(tasks, "user_batch_lock", _locked),
        caplog.at_level(logging.INFO),
    ):
        tasks.run_user_batch(1)

    messages = [r.message for r in caplog.records]
    assert any("skipped: locked" in m for m in messages)
    assert not any("run_user_batch start" in m for m in messages)


def test_run_user_batch_runs_when_acquired() -> None:
    @contextmanager
    def _acquired(*_args: object, **_kwargs: object) -> Iterator[bool]:
        yield True

    with _patch_redis(), patch.object(tasks, "user_batch_lock", _acquired):
        # Placeholder body (seam): must not raise.
        tasks.run_user_batch(1)


def test_run_user_batch_no_op_while_real_lock_held() -> None:
    """End-to-end against fakeredis: a held lock makes a second batch a no-op."""
    redis = fakeredis.FakeRedis()
    # Simulate an in-flight batch holding the lock.
    assert acquire_user_batch_lock(redis, 9, "in-flight", 600) is True

    with patch.object(tasks, "get_redis_client", return_value=redis):
        # Second batch for the same user contends → clean no-op, no exception.
        tasks.run_user_batch(9)
