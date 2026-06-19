"""TASK-102 — persistent dead-session quarantine across worker restarts.

The quarantine (TASK-087) was in-memory only; a worker restart/recycle un-quarantined
dead sessions. These tests verify the Redis-backed persistence by NON-SECRET fingerprint:
load-on-init, persist-on-quarantine, fail-open on Redis error, re-mint recovery, and the
redis=None backward-compatible path.
"""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import MagicMock

import fakeredis
from redis.exceptions import RedisError

from collector.constants import QUARANTINE_REDIS_KEY
from collector.telegram.account_pool import AccountPool, session_fingerprint
from collector.telegram.client import TelegramClientProtocol

from .conftest import FakeClient


def _factory_for(sessions: list[str]) -> Callable[[str, str | None], TelegramClientProtocol]:
    clients = iter([FakeClient() for _ in sessions])
    # TASK-129: factory accepts optional proxy arg (2-arg signature).
    return lambda _session, _proxy=None: next(clients)


def _pool(sessions: list[str], redis: object | None) -> AccountPool:
    return AccountPool.from_sessions(sessions=sessions, factory=_factory_for(sessions), redis=redis)


def test_session_fingerprint_is_stable_and_non_secret() -> None:
    s = "1AbCmy-secret-telethon-string-xyz"
    fp = session_fingerprint(s)
    assert fp == session_fingerprint(s)  # deterministic
    assert len(fp) == 16  # sha256[:16]
    assert s not in fp and fp not in s  # one-way: never contains the session
    assert session_fingerprint("a-different-session") != fp  # changes per session (re-mint)


def test_load_marks_persisted_fingerprint_quarantined() -> None:
    r = fakeredis.FakeRedis()
    r.sadd(QUARANTINE_REDIS_KEY, session_fingerprint("sess-a"))
    pool = _pool(["sess-a", "sess-b"], r)
    assert pool.quarantined_count == 1
    # acquire only ever hands out the LIVE session (sess-b's client), never the dead one.
    acquired = {pool.acquire() for _ in range(4)}
    assert len(acquired) == 1  # sess-b only


def test_quarantine_current_persists_fingerprint_with_ttl() -> None:
    r = fakeredis.FakeRedis()
    pool = _pool(["sess-a"], r)
    pool.acquire()
    pool.quarantine_current()
    assert r.sismember(QUARANTINE_REDIS_KEY, session_fingerprint("sess-a"))
    assert r.ttl(QUARANTINE_REDIS_KEY) > 0


def test_load_fail_open_on_redis_error() -> None:
    r = MagicMock()
    r.smembers.side_effect = RedisError("redis down")
    pool = _pool(["sess-a", "sess-b"], r)
    assert pool.quarantined_count == 0  # fail-open: built in-memory-only, no crash


def test_persist_fail_open_on_redis_error() -> None:
    r = MagicMock()
    r.smembers.return_value = set()
    r.pipeline.return_value.execute.side_effect = RedisError("redis down")
    pool = _pool(["sess-a"], r)
    pool.acquire()
    pool.quarantine_current()  # must not raise despite the pipeline execute failure
    assert pool.quarantined_count == 1  # in-memory quarantine still holds


def test_reminted_session_is_not_quarantined() -> None:
    r = fakeredis.FakeRedis()
    r.sadd(QUARANTINE_REDIS_KEY, session_fingerprint("old-dead-session"))
    pool = _pool(["freshly-reminted-session"], r)  # different fingerprint
    assert pool.quarantined_count == 0  # re-minted session loads live (auto-recovery)


def test_malformed_persisted_member_is_ignored() -> None:
    """Defense-in-depth: a corrupted/poisoned set member that isn't a valid fingerprint
    must not match (or crash) — only the well-formed fingerprint quarantines."""
    r = fakeredis.FakeRedis()
    r.sadd(QUARANTINE_REDIS_KEY, b"not-a-real-fingerprint!!", session_fingerprint("sess-a"))
    pool = _pool(["sess-a", "sess-b"], r)
    assert pool.quarantined_count == 1  # only sess-a (valid fp); junk ignored


def test_no_redis_is_in_memory_only_backward_compat() -> None:
    pool = _pool(["sess-a"], None)  # redis=None → today's behavior
    pool.acquire()
    pool.quarantine_current()  # no persistence, must not raise
    assert pool.quarantined_count == 1
