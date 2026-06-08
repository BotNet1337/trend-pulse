"""AC1 (RED-first) — per-user batch lock: acquire / contend / release / foreign-release.

The lock is the sole arbiter of `max_instances=1` for a single user's batch
(ADR-002): a second `run_user_batch` for the same `user_id` must not start while
the first holds the lock. Tested against fakeredis (no live infra).
"""

import fakeredis

from pipeline.locks import (
    acquire_user_batch_lock,
    batch_lock_key,
    release_user_batch_lock,
    user_batch_lock,
)

# Explicit test TTL (the lock now resolves its default lazily from settings).
BATCH_LOCK_TTL_SECONDS = 600


def test_acquire_then_contend_returns_false() -> None:
    redis = fakeredis.FakeRedis()
    assert acquire_user_batch_lock(redis, 1, "token-a", BATCH_LOCK_TTL_SECONDS) is True
    # Second acquire for the SAME user without release → contended.
    assert acquire_user_batch_lock(redis, 1, "token-b", BATCH_LOCK_TTL_SECONDS) is False


def test_release_lets_next_acquire_succeed() -> None:
    redis = fakeredis.FakeRedis()
    assert acquire_user_batch_lock(redis, 1, "token-a", BATCH_LOCK_TTL_SECONDS) is True
    assert release_user_batch_lock(redis, 1, "token-a") is True
    # After release the lock is free again.
    assert acquire_user_batch_lock(redis, 1, "token-b", BATCH_LOCK_TTL_SECONDS) is True


def test_release_with_wrong_token_does_not_release() -> None:
    redis = fakeredis.FakeRedis()
    assert acquire_user_batch_lock(redis, 1, "token-a", BATCH_LOCK_TTL_SECONDS) is True
    # A foreign token must NOT release someone else's lock.
    assert release_user_batch_lock(redis, 1, "token-b") is False
    # Lock is still held → a fresh acquire still contends.
    assert acquire_user_batch_lock(redis, 1, "token-c", BATCH_LOCK_TTL_SECONDS) is False


def test_acquire_sets_ttl() -> None:
    redis = fakeredis.FakeRedis()
    acquire_user_batch_lock(redis, 7, "token-a", BATCH_LOCK_TTL_SECONDS)
    ttl = redis.ttl(batch_lock_key(7))
    assert 0 < ttl <= BATCH_LOCK_TTL_SECONDS


def test_locks_are_per_user_independent() -> None:
    redis = fakeredis.FakeRedis()
    assert acquire_user_batch_lock(redis, 1, "token-a", BATCH_LOCK_TTL_SECONDS) is True
    # A different user's lock is independent.
    assert acquire_user_batch_lock(redis, 2, "token-b", BATCH_LOCK_TTL_SECONDS) is True


def test_context_manager_acquires_and_releases() -> None:
    redis = fakeredis.FakeRedis()
    with user_batch_lock(redis, 1) as acquired:
        assert acquired is True
        # While held, a direct acquire contends.
        assert acquire_user_batch_lock(redis, 1, "other", BATCH_LOCK_TTL_SECONDS) is False
    # On exit the lock is released → free to acquire again.
    assert acquire_user_batch_lock(redis, 1, "after", BATCH_LOCK_TTL_SECONDS) is True


def test_context_manager_yields_false_when_locked() -> None:
    redis = fakeredis.FakeRedis()
    assert acquire_user_batch_lock(redis, 1, "held", BATCH_LOCK_TTL_SECONDS) is True
    with user_batch_lock(redis, 1) as acquired:
        # Could not acquire — already held by another holder.
        assert acquired is False
    # The other holder's lock must survive a non-acquiring context's exit.
    assert acquire_user_batch_lock(redis, 1, "again", BATCH_LOCK_TTL_SECONDS) is False
