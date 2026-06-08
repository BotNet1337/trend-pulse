"""Per-user batch lock on Redis — the sole arbiter of `max_instances=1` (ADR-002).

A user's batch must never run twice in parallel. The lock is acquired with
``SET key token NX EX ttl`` (atomic, always with a finite TTL so a crashed worker
cannot deadlock forever — edge case in task-006). Release is owner-checked via an
atomic ``WATCH``/``MULTI`` compare-and-delete: a holder only ever drops *its own*
lock, never one re-acquired by another worker after a TTL expiry (token mismatch
→ no-op). The CAS is server-atomic (optimistic locking aborts on concurrent
mutation) yet needs no server-side Lua, so unit tests run on fakeredis.

The Redis client is supplied by the caller (taken from ``storage`` — cross-module
via the service interface, CONVENTIONS); only the minimal surface is depended on,
so tests can drive this with fakeredis.
"""

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from redis import Redis
from redis.client import Pipeline

from config import get_settings

logger = logging.getLogger(__name__)

_KEY_PREFIX = "lock:batch:user"


def batch_lock_key(user_id: int) -> str:
    """Return the Redis key for a user's batch lock: ``lock:batch:user:{id}``."""
    return f"{_KEY_PREFIX}:{user_id}"


def acquire_user_batch_lock(redis: Redis, user_id: int, token: str, ttl: int) -> bool:
    """Try to acquire the batch lock for ``user_id``.

    Uses ``SET NX EX`` so the write + TTL are atomic. Returns ``True`` when the
    lock was taken by this ``token``, ``False`` when another holder already has it.
    """
    acquired = redis.set(batch_lock_key(user_id), token, nx=True, ex=ttl)
    return acquired is True


def release_user_batch_lock(redis: Redis, user_id: int, token: str) -> bool:
    """Release the batch lock for ``user_id`` only if ``token`` still owns it.

    Owner-checked compare-and-delete via ``Redis.transaction`` (WATCH/MULTI under
    the hood): the callback reads the key and only queues a ``DEL`` when it still
    holds our token; the WATCH aborts the transaction if another client mutated
    the key meanwhile, so we never delete a lock re-acquired by someone else. The
    outcome is captured in a closure (the redis-py stub types ``transaction`` as
    returning ``None``, so we do not rely on its return value). Returns ``True``
    when this token's lock was deleted, ``False`` on a token mismatch (foreign
    lock — left untouched) or when the key was already gone.
    """
    key = batch_lock_key(user_id)
    expected = token.encode()
    deleted = False

    def _cas(pipe: Pipeline) -> None:
        nonlocal deleted
        current = pipe.get(key)
        pipe.multi()
        # Recompute each invocation: redis-py re-runs this callback on a WATCH
        # retry, so the flag must reflect only the final, committed attempt.
        deleted = current == expected
        if deleted:
            pipe.delete(key)

    redis.transaction(_cas, key)
    return deleted


@contextmanager
def user_batch_lock(redis: Redis, user_id: int, ttl: int | None = None) -> Iterator[bool]:
    """Context manager wrapping acquire/release of a user's batch lock.

    Yields ``True`` if the lock was acquired (and releases it on exit), or
    ``False`` if it was already held — in which case it must NOT release the
    foreign lock. The unique per-acquisition ``token`` guarantees ownership.
    TTL is resolved lazily from settings (named value, never a magic literal —
    CONVENTIONS) so importing this module needs no env/Settings at import time.
    """
    resolved_ttl = ttl if ttl is not None else get_settings().batch_lock_ttl_seconds
    token = uuid.uuid4().hex
    acquired = acquire_user_batch_lock(redis, user_id, token, resolved_ttl)
    try:
        yield acquired
    finally:
        if acquired:
            release_user_batch_lock(redis, user_id, token)
