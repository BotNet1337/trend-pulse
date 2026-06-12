"""Global collect-tick lock on Redis — `max_instances=1` for ingest.

There is ONE Telethon session pool per deployment; two overlapping collect
ticks would hammer the same accounts (FLOOD_WAIT) and double-write the raw
buffer. The lock follows `pipeline.locks` (the per-user batch lock) exactly,
but with a single GLOBAL key: acquire is an atomic ``SET key token NX EX ttl``
(always a finite TTL so a crashed worker cannot deadlock ingest forever);
release is an owner-checked compare-and-delete via ``WATCH``/``MULTI`` so a
holder only ever drops *its own* lock, never one re-acquired after TTL expiry.
Runs on fakeredis in unit tests (no server-side Lua).
"""

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from redis import Redis
from redis.client import Pipeline

from config import get_settings

logger = logging.getLogger(__name__)

_LOCK_KEY = "lock:collect:tick"


def collect_lock_key() -> str:
    """Return the Redis key of the global collect-tick lock."""
    return _LOCK_KEY


def acquire_collect_tick_lock(redis: Redis, token: str, ttl: int) -> bool:
    """Try to acquire the global collect-tick lock (``SET NX EX`` — atomic).

    Returns ``True`` when the lock was taken by this ``token``, ``False`` when
    another holder (an in-flight tick) already has it.
    """
    acquired = redis.set(_LOCK_KEY, token, nx=True, ex=ttl)
    return acquired is True


def release_collect_tick_lock(redis: Redis, token: str) -> bool:
    """Release the collect-tick lock only if ``token`` still owns it.

    Owner-checked compare-and-delete via ``Redis.transaction`` (WATCH/MULTI):
    the callback only queues a ``DEL`` while our token still holds the key; the
    WATCH aborts on concurrent mutation, so a lock re-acquired by another tick
    after TTL expiry is never deleted. Returns ``True`` when this token's lock
    was dropped, ``False`` on token mismatch / already-expired key.
    """
    expected = token.encode()
    deleted = False

    def _cas(pipe: Pipeline) -> None:
        nonlocal deleted
        current = pipe.get(_LOCK_KEY)
        pipe.multi()
        # Recompute each invocation: redis-py re-runs the callback on a WATCH
        # retry, so the flag must reflect only the final committed attempt.
        deleted = current == expected
        if deleted:
            pipe.delete(_LOCK_KEY)

    redis.transaction(_cas, _LOCK_KEY)
    return deleted


@contextmanager
def collect_tick_lock(redis: Redis, ttl: int | None = None) -> Iterator[bool]:
    """Context manager around acquire/release of the global collect-tick lock.

    Yields ``True`` if the lock was acquired (released on exit) or ``False`` if
    an in-flight tick holds it — in which case the foreign lock is left alone.
    TTL resolves lazily from settings (`collect_lock_ttl_seconds`, never a magic
    literal — CONVENTIONS) so importing this module needs no env at import time.
    """
    resolved_ttl = ttl if ttl is not None else get_settings().collect_lock_ttl_seconds
    token = uuid.uuid4().hex
    acquired = acquire_collect_tick_lock(redis, token, resolved_ttl)
    try:
        yield acquired
    finally:
        if acquired:
            release_collect_tick_lock(redis, token)
