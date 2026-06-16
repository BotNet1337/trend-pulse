"""TASK-119 — SAFE single-slot live revive (the ADR safety case, unit-asserted).

The two guarantees the entire ADR rests on, each proven here with fake clients:
  1. A session is NEVER connected by two clients at once — the OLD client is
     `disconnect()`ed BEFORE the NEW client `connect()`s (global call-order log).
  2. Only the ONE affected slot churns — every other slot's client is untouched
     (no connect/disconnect on siblings; their client object is identical).

Plus: the revived slot's transient state (quarantined/cooldown/read-outcome) is
reset so it leaves `failing`/`quarantined`; a failed OLD disconnect does not block
the revive; find_slot_index locates by tg_user_id then fingerprint.
"""

from __future__ import annotations

import fakeredis
import pytest

from collector.constants import QUARANTINE_REDIS_KEY
from collector.errors import PoolConfigError
from collector.telegram.account_pool import AccountPool, session_fingerprint

_SESSION_OLD = "1AbCsession-OLD-account-a"
_SESSION_NEW = "1AbCsession-NEW-account-a-reminted"
_SESSION_SIBLING = "1AbCsession-sibling-b"


class _RecordingClient:
    """Fake client that appends every connect/disconnect to a SHARED ordered log."""

    def __init__(self, name: str, log: list[str], *, disconnect_raises: bool = False) -> None:
        self.name = name
        self._log = log
        self._disconnect_raises = disconnect_raises
        self.connect_calls = 0
        self.disconnect_calls = 0
        self._connected = False

    async def connect(self) -> None:
        self.connect_calls += 1
        self._connected = True
        self._log.append(f"connect:{self.name}")

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False
        self._log.append(f"disconnect:{self.name}")
        if self._disconnect_raises:
            raise RuntimeError("dead socket disconnect failed")

    def is_connected(self) -> bool:
        return self._connected


def _build_pool(
    log: list[str], new_client: _RecordingClient
) -> tuple[AccountPool, _RecordingClient, _RecordingClient]:
    """Pool with two slots; the factory hands out `new_client` for the NEW session."""
    old = _RecordingClient("old", log)
    sibling = _RecordingClient("sibling", log)

    def factory(session: str) -> _RecordingClient:
        if session == _SESSION_OLD:
            return old
        if session == _SESSION_SIBLING:
            return sibling
        if session == _SESSION_NEW:
            return new_client
        raise AssertionError(f"unexpected session {session!r}")

    pool = AccountPool.from_sessions(
        sessions=[_SESSION_OLD, _SESSION_SIBLING],
        factory=factory,
        tg_user_ids=[111, 222],
    )
    return pool, old, sibling


async def test_revive_disconnects_old_before_connecting_new() -> None:
    log: list[str] = []
    new = _RecordingClient("new", log)
    pool, old, _sibling = _build_pool(log, new)

    slot = pool.find_slot_index(tg_user_id=111, fingerprint=session_fingerprint(_SESSION_OLD))
    assert slot == 0
    await pool.revive_slot(slot_index=slot, tg_user_id=111, session_string=_SESSION_NEW)

    # INVARIANT 1: old disconnect strictly precedes new connect (never two live at once).
    assert "disconnect:old" in log
    assert "connect:new" in log
    assert log.index("disconnect:old") < log.index("connect:new")
    assert old.disconnect_calls == 1
    assert new.connect_calls == 1


async def test_revive_touches_only_target_slot() -> None:
    log: list[str] = []
    new = _RecordingClient("new", log)
    pool, _old, sibling = _build_pool(log, new)

    await pool.revive_slot(slot_index=0, tg_user_id=111, session_string=_SESSION_NEW)

    # INVARIANT 2: the sibling slot's client was never connected/disconnected.
    assert sibling.connect_calls == 0
    assert sibling.disconnect_calls == 0
    assert "connect:sibling" not in log
    assert "disconnect:sibling" not in log


async def test_revive_swaps_client_and_resets_state() -> None:
    log: list[str] = []
    new = _RecordingClient("new", log)
    pool, _old, _sibling = _build_pool(log, new)

    # Make the target slot quarantined + cooling + failing first.
    pool.acquire()  # index 0
    pool.quarantine_current()
    statuses_before = pool.account_statuses()
    assert statuses_before[0].state == "quarantined"

    await pool.revive_slot(slot_index=0, tg_user_id=111, session_string=_SESSION_NEW)

    statuses = pool.account_statuses()
    assert statuses[0].state == "healthy"  # left quarantined/failing
    assert statuses[0].last_error_reason == ""
    # The revived slot's client object IS the new client (swapped in place).
    assert pool._accounts[0].client is new
    assert pool._accounts[0].quarantined is False
    assert pool._accounts[0].cooldown_until == 0.0
    assert pool._accounts[0].consecutive_read_failures == 0


async def test_revive_updates_fingerprint_and_identity() -> None:
    log: list[str] = []
    new = _RecordingClient("new", log)
    pool, _old, _sibling = _build_pool(log, new)

    await pool.revive_slot(slot_index=0, tg_user_id=111, session_string=_SESSION_NEW)
    # The slot now matches the NEW fingerprint (so it won't be reloaded as the old dead).
    assert pool.find_slot_index(tg_user_id=111, fingerprint=session_fingerprint(_SESSION_NEW)) == 0


async def test_revive_proceeds_when_old_disconnect_raises() -> None:
    """A failed disconnect on a dead socket must not block connecting the new client."""
    log: list[str] = []
    new = _RecordingClient("new", log)
    old = _RecordingClient("old", log, disconnect_raises=True)
    sibling = _RecordingClient("sibling", log)

    def factory(session: str) -> _RecordingClient:
        return {
            _SESSION_OLD: old,
            _SESSION_SIBLING: sibling,
            _SESSION_NEW: new,
        }[session]

    pool = AccountPool.from_sessions(
        sessions=[_SESSION_OLD, _SESSION_SIBLING],
        factory=factory,
        tg_user_ids=[111, 222],
    )
    await pool.revive_slot(slot_index=0, tg_user_id=111, session_string=_SESSION_NEW)
    assert new.connect_calls == 1  # proceeded despite the disconnect failure
    assert log.index("disconnect:old") < log.index("connect:new")


async def test_revive_out_of_range_raises() -> None:
    log: list[str] = []
    new = _RecordingClient("new", log)
    pool, _old, _sibling = _build_pool(log, new)
    with pytest.raises(PoolConfigError):
        await pool.revive_slot(slot_index=9, tg_user_id=111, session_string=_SESSION_NEW)


async def test_revive_clears_old_fingerprint_from_persisted_quarantine() -> None:
    """TASK-119 MEDIUM fix (belt-and-suspenders): revive_slot SREMs the swapped-out OLD
    fingerprint from `pool:quarantined_fingerprints` so a worker recycle after the revive
    cannot reload the slot as dead even if the producer's clear was skipped/failed."""
    log: list[str] = []
    new = _RecordingClient("new", log)
    old = _RecordingClient("old", log)
    sibling = _RecordingClient("sibling", log)

    def factory(session: str) -> _RecordingClient:
        return {_SESSION_OLD: old, _SESSION_SIBLING: sibling, _SESSION_NEW: new}[session]

    r = fakeredis.FakeRedis()
    old_fp = session_fingerprint(_SESSION_OLD)
    # Seed the persisted quarantine with the OLD fingerprint (as a worker recycle would).
    r.sadd(QUARANTINE_REDIS_KEY, old_fp)
    pool = AccountPool.from_sessions(
        sessions=[_SESSION_OLD, _SESSION_SIBLING],
        factory=factory,
        redis=r,
        tg_user_ids=[111, 222],
    )

    await pool.revive_slot(slot_index=0, tg_user_id=111, session_string=_SESSION_NEW)

    # The OLD fingerprint is gone from the persisted set; the sibling's is untouched.
    assert not r.sismember(QUARANTINE_REDIS_KEY, old_fp)


async def test_revive_quarantine_clear_fails_open_without_redis() -> None:
    """No redis on the pool → the SREM is a silent no-op (revive still succeeds)."""
    log: list[str] = []
    new = _RecordingClient("new", log)
    pool, _old, _sibling = _build_pool(log, new)  # built without redis
    await pool.revive_slot(slot_index=0, tg_user_id=111, session_string=_SESSION_NEW)
    assert pool._accounts[0].client is new  # revive succeeded


def test_find_slot_index_falls_back_to_fingerprint() -> None:
    log: list[str] = []
    new = _RecordingClient("new", log)
    pool, _old, _sibling = _build_pool(log, new)
    # tg_user_id not present → fall back to the OLD fingerprint.
    assert pool.find_slot_index(tg_user_id=None, fingerprint=session_fingerprint(_SESSION_OLD)) == 0
    assert pool.find_slot_index(tg_user_id=None, fingerprint="deadbeefdeadbeef") is None
