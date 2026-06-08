"""G2 / AC7 — Celery tasks execute against a real Redis broker (eager + live).

Marked `integration` so `make ci-fast` (`-m 'not integration'`) never runs it.
Most assertions use Celery's eager mode (in-process, real serialization) so they
need no worker; the live-Redis check is guarded and skipped when Redis is absent.
"""

from collections.abc import Iterator

import pytest
import redis as redis_lib

from celery_app import celery_app
from config import get_settings
from pipeline import tasks
from pipeline.locks import acquire_user_batch_lock, batch_lock_key

pytestmark = pytest.mark.integration


@pytest.fixture
def eager() -> Iterator[None]:
    """Run tasks in-process with real (de)serialization; propagate errors."""
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    try:
        yield
    finally:
        celery_app.conf.task_always_eager = False
        celery_app.conf.task_eager_propagates = False


def _redis_or_skip() -> redis_lib.Redis:
    client = redis_lib.Redis.from_url(get_settings().redis_url)
    try:
        client.ping()
    except redis_lib.exceptions.RedisError:
        pytest.skip("Redis not reachable for integration test")
    return client


def test_run_user_batch_delay_json_serializable(eager: None) -> None:
    # Eager execution runs the body, which acquires the per-user Redis lock — needs
    # a reachable Redis. JSON serializer rejects non-serializable args; an int passes.
    _redis_or_skip()
    result = tasks.run_user_batch.delay(1)
    assert result.get(timeout=5) is None


def test_score_tick_delay(eager: None) -> None:
    # Eager body scores clusters + enqueues delivery — touches Redis; skip if absent.
    _redis_or_skip()
    result = tasks.score_tick.delay()
    assert result.get(timeout=5) is None


def test_run_user_batch_skips_when_lock_held_real_redis(eager: None) -> None:
    client = _redis_or_skip()
    user_id = 424242
    client.delete(batch_lock_key(user_id))
    try:
        assert acquire_user_batch_lock(client, user_id, "held", 600) is True
        # Lock held → second batch is a clean no-op (does not raise, AC2).
        tasks.run_user_batch.delay(user_id).get(timeout=5)
        # The foreign lock survived (we never released it).
        assert client.get(batch_lock_key(user_id)) == b"held"
    finally:
        client.delete(batch_lock_key(user_id))
