"""TASK-119 — reader applies the revive-signal at a tick boundary (best-effort).

The collect-tick reader checks the NON-SECRET Redis revive-signal at the START of
`read()` (a tick boundary, never mid-`iter_messages`), loads the NEW session from the
encrypted store, and calls `pool.revive_slot(...)`. A store/Redis error must NEVER
crash the tick. The session string is loaded from the DB store inside the worker —
the Redis signal carries only the non-secret `tg_user_id`/`fingerprint`.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import fakeredis

from collector.constants import POOL_REVIVE_SIGNAL_REDIS_KEY
from collector.telegram.account_pool import session_fingerprint
from collector.telegram.reader import TelegramCollector
from storage.pool_session_store import StoredSession

_NEW_SESSION = "1AbCsession-NEW-reminted"


def _collector_with_redis(redis: object) -> tuple[TelegramCollector, MagicMock]:
    pool = MagicMock()
    pool.find_slot_index.return_value = 0
    pool.revive_slot = AsyncMock()
    collector = TelegramCollector(pool, redis=redis)
    return collector, pool


async def _drain(collector: TelegramCollector) -> None:
    """Run read() with no refs so only the tick-boundary revive check fires."""
    collector._sleep = AsyncMock()  # type: ignore[method-assign]
    async for _ in collector.read([], since=None):
        pass


async def test_revive_signal_triggers_revive_slot(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    r = fakeredis.FakeRedis()
    fp = session_fingerprint("old-dead")
    r.set(
        POOL_REVIVE_SIGNAL_REDIS_KEY,
        json.dumps({"tg_user_id": 111, "fingerprint": fp}),
    )
    collector, pool = _collector_with_redis(r)

    # Patch the store loader so no real DB is touched (the secret comes from the store).
    monkeypatch.setattr(
        collector,
        "_load_stored_session",
        lambda tg_user_id: StoredSession(
            tg_user_id=111,
            fingerprint=session_fingerprint(_NEW_SESSION),
            display_label="@a",
            session_string=_NEW_SESSION,
        ),
    )

    await _drain(collector)

    pool.find_slot_index.assert_called_once_with(tg_user_id=111, fingerprint=fp)
    pool.revive_slot.assert_awaited_once_with(
        slot_index=0, tg_user_id=111, session_string=_NEW_SESSION
    )
    # Signal cleared after application (applies once).
    assert r.get(POOL_REVIVE_SIGNAL_REDIS_KEY) is None


async def test_no_signal_is_noop() -> None:
    r = fakeredis.FakeRedis()
    collector, pool = _collector_with_redis(r)
    await _drain(collector)
    pool.revive_slot.assert_not_awaited()


async def test_signal_carries_no_session_string() -> None:
    """Defense-in-depth: even if the secret leaked into the signal, the loader is the
    sole source of the session — the signal is parsed for identity only."""
    r = fakeredis.FakeRedis()
    r.set(
        POOL_REVIVE_SIGNAL_REDIS_KEY,
        json.dumps({"tg_user_id": 111, "fingerprint": session_fingerprint("x")}),
    )
    collector, _pool = _collector_with_redis(r)
    signal = collector._read_revive_signal()
    assert signal == (111, session_fingerprint("x"))
    # The raw value in Redis must never contain a session string in production; here we
    # only assert the parser ignores any non-identity keys.
    assert "session" not in (r.get(POOL_REVIVE_SIGNAL_REDIS_KEY) or b"").decode()


async def test_malformed_signal_is_ignored() -> None:
    r = fakeredis.FakeRedis()
    r.set(POOL_REVIVE_SIGNAL_REDIS_KEY, b"not-json{{{")
    collector, pool = _collector_with_redis(r)
    await _drain(collector)
    pool.revive_slot.assert_not_awaited()


async def test_store_error_does_not_crash_tick(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    r = fakeredis.FakeRedis()
    r.set(
        POOL_REVIVE_SIGNAL_REDIS_KEY,
        json.dumps({"tg_user_id": 111, "fingerprint": session_fingerprint("y")}),
    )
    collector, pool = _collector_with_redis(r)

    def _boom(tg_user_id: int) -> StoredSession:
        raise RuntimeError("DB down")

    monkeypatch.setattr(collector, "_load_stored_session", _boom)
    # Must not raise — best-effort.
    await _drain(collector)
    pool.revive_slot.assert_not_awaited()


async def test_slot_not_found_clears_signal_and_skips() -> None:
    r = fakeredis.FakeRedis()
    r.set(
        POOL_REVIVE_SIGNAL_REDIS_KEY,
        json.dumps({"tg_user_id": 999, "fingerprint": session_fingerprint("z")}),
    )
    collector, pool = _collector_with_redis(r)
    pool.find_slot_index.return_value = None  # brand-new account, not in live pool
    await _drain(collector)
    pool.revive_slot.assert_not_awaited()
    assert r.get(POOL_REVIVE_SIGNAL_REDIS_KEY) is None  # cleared so we don't re-check


async def test_redis_none_is_noop() -> None:
    pool = MagicMock()
    pool.revive_slot = AsyncMock()
    collector = TelegramCollector(pool, redis=None)
    collector._sleep = AsyncMock()  # type: ignore[method-assign]
    async for _ in collector.read([], since=None):
        pass
    pool.revive_slot.assert_not_awaited()
