"""TASK-119 — dynamic pool session store (upsert revive/add, active, quarantine).

Exercises the store against an in-memory SQLite (the `EncryptedString` TypeDecorator
works over SQLite VARCHAR — the at-rest-ciphertext assertion against a real Postgres
column lives in the integration migration test). Covers:
  * ADD inserts a new row keyed by tg_user_id; outcome=ADD.
  * the stored session is ENCRYPTED at rest (raw column value != plaintext).
  * REVIVE replaces session+fingerprint, clears revoked_at, returns the OLD
    fingerprint, and never duplicates the row; outcome=REVIVE.
  * over-cap ADD raises PoolCapacityExceededError; a revive over cap is allowed.
  * active_sessions filters soft-revoked rows; revoke is idempotent.
  * clear_quarantine_for removes the old fingerprint (and fail-opens on Redis error).
"""

from __future__ import annotations

from collections.abc import Iterator

import fakeredis
import pytest
from sqlalchemy import StaticPool, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from collector.constants import QUARANTINE_REDIS_KEY
from collector.errors import PoolCapacityExceededError
from collector.telegram.account_pool import session_fingerprint
from storage.models.base import Base
from storage.pool_session_store import (
    ReviveOutcome,
    active_sessions,
    clear_quarantine_for,
    find_active_by_tg_user_id,
    revoke,
    upsert_revive_or_add,
)

_SESSION_A = "1AbCsession-string-account-a-xyz"
_SESSION_A2 = "1AbCsession-string-account-a-REMINTED"
_SESSION_B = "1AbCsession-string-account-b-xyz"
_POOL_MAX = 3


@pytest.fixture
def db() -> Iterator[Session]:
    """In-memory SQLite with the full schema (single shared connection)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = factory()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def test_add_inserts_new_row_with_outcome_add(db: Session) -> None:
    result = upsert_revive_or_add(
        db, tg_user_id=111, session_string=_SESSION_A, display_label="@alice", pool_max=_POOL_MAX
    )
    assert result.outcome is ReviveOutcome.ADD
    assert result.tg_user_id == 111
    assert result.fingerprint == session_fingerprint(_SESSION_A)
    assert result.previous_fingerprint is None
    active = active_sessions(db)
    assert len(active) == 1
    assert active[0].session_string == _SESSION_A  # ORM decrypts


def test_session_is_encrypted_at_rest(db: Session) -> None:
    """The raw DB column value must be a Fernet token, not the plaintext session."""
    upsert_revive_or_add(
        db, tg_user_id=111, session_string=_SESSION_A, display_label="@alice", pool_max=_POOL_MAX
    )
    db.commit()
    raw = db.execute(
        text("SELECT session_string FROM pool_sessions WHERE tg_user_id = 111")
    ).scalar()
    assert raw is not None
    assert raw != _SESSION_A, "plaintext session leaked into the DB column"
    assert raw.startswith("gAA"), "DB column is not a Fernet ciphertext token"


def test_revive_replaces_session_and_clears_revoked(db: Session) -> None:
    upsert_revive_or_add(
        db, tg_user_id=111, session_string=_SESSION_A, display_label="@alice", pool_max=_POOL_MAX
    )
    revoke(db, tg_user_id=111)  # simulate an expired/kicked account
    assert active_sessions(db) == []  # filtered out while revoked

    result = upsert_revive_or_add(
        db, tg_user_id=111, session_string=_SESSION_A2, display_label="@alice2", pool_max=_POOL_MAX
    )
    assert result.outcome is ReviveOutcome.REVIVE
    assert result.previous_fingerprint == session_fingerprint(_SESSION_A)
    assert result.fingerprint == session_fingerprint(_SESSION_A2)
    # SAME row, no duplicate; revoked cleared → active again with the NEW session.
    active = active_sessions(db)
    assert len(active) == 1
    assert active[0].session_string == _SESSION_A2
    assert active[0].display_label == "@alice2"
    # Exactly one row for this account (no duplicate insert).
    count = db.execute(text("SELECT COUNT(*) FROM pool_sessions WHERE tg_user_id = 111")).scalar()
    assert count == 1


def test_over_cap_add_raises(db: Session) -> None:
    for i in range(_POOL_MAX):
        upsert_revive_or_add(
            db,
            tg_user_id=100 + i,
            session_string=f"1AbCsession-{i}",
            display_label=f"@u{i}",
            pool_max=_POOL_MAX,
        )
    with pytest.raises(PoolCapacityExceededError):
        upsert_revive_or_add(
            db,
            tg_user_id=999,
            session_string=_SESSION_B,
            display_label="@over",
            pool_max=_POOL_MAX,
        )


def test_revive_over_cap_is_allowed(db: Session) -> None:
    """A revive of an EXISTING account never trips the cap (it replaces in place)."""
    for i in range(_POOL_MAX):
        upsert_revive_or_add(
            db,
            tg_user_id=100 + i,
            session_string=f"1AbCsession-{i}",
            display_label=f"@u{i}",
            pool_max=_POOL_MAX,
        )
    # Re-scan the SAME account 100 → revive, even though we are at POOL_MAX.
    result = upsert_revive_or_add(
        db, tg_user_id=100, session_string=_SESSION_A2, display_label="@u0", pool_max=_POOL_MAX
    )
    assert result.outcome is ReviveOutcome.REVIVE


def test_active_sessions_filters_revoked_and_revoke_idempotent(db: Session) -> None:
    upsert_revive_or_add(
        db, tg_user_id=111, session_string=_SESSION_A, display_label="@a", pool_max=_POOL_MAX
    )
    upsert_revive_or_add(
        db, tg_user_id=222, session_string=_SESSION_B, display_label="@b", pool_max=_POOL_MAX
    )
    assert len(active_sessions(db)) == 2
    assert revoke(db, tg_user_id=111) is True
    assert revoke(db, tg_user_id=111) is True  # idempotent
    assert revoke(db, tg_user_id=404) is False  # unknown
    active = active_sessions(db)
    assert len(active) == 1
    assert active[0].tg_user_id == 222


def test_find_active_by_tg_user_id(db: Session) -> None:
    upsert_revive_or_add(
        db, tg_user_id=111, session_string=_SESSION_A, display_label="@a", pool_max=_POOL_MAX
    )
    found = find_active_by_tg_user_id(db, 111)
    assert found is not None
    assert found.session_string == _SESSION_A
    assert find_active_by_tg_user_id(db, 404) is None
    revoke(db, tg_user_id=111)
    assert find_active_by_tg_user_id(db, 111) is None  # revoked → not active


def test_clear_quarantine_for_removes_old_fingerprint() -> None:
    r = fakeredis.FakeRedis()
    old_fp = session_fingerprint(_SESSION_A)
    r.sadd(QUARANTINE_REDIS_KEY, old_fp)
    clear_quarantine_for(r, old_fp)
    assert not r.sismember(QUARANTINE_REDIS_KEY, old_fp)


def test_clear_quarantine_for_ignores_malformed_and_none() -> None:
    r = fakeredis.FakeRedis()
    clear_quarantine_for(r, "not-a-valid-fp")  # malformed → no-op, no raise
    clear_quarantine_for(None, session_fingerprint(_SESSION_A))  # redis=None → no-op


def test_stored_session_repr_hides_secret(db: Session) -> None:
    """The session string must never appear in a StoredSession repr (secret)."""
    upsert_revive_or_add(
        db, tg_user_id=111, session_string=_SESSION_A, display_label="@a", pool_max=_POOL_MAX
    )
    stored = active_sessions(db)[0]
    assert _SESSION_A not in repr(stored)
    assert stored.session_string == _SESSION_A  # still accessible
