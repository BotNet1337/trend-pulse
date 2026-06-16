"""TASK-119 — pool session store integration (encrypted at rest on real Postgres).

Validates against a live pgvector Postgres (see conftest.py recipe):
  * the minted session is stored as Fernet ciphertext (raw SELECT != plaintext),
    while the ORM read returns the plaintext (TypeDecorator round-trip).
  * upsert REVIVE vs ADD semantics persist across sessions.
  * the union loader (`registry._union_pool_sessions`) merges env + DB store,
    de-duped by fingerprint, with the DB row's identity carried.

Marker: integration. Requires live pgvector Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from collector.telegram.account_pool import session_fingerprint
from storage.pool_session_store import (
    ReviveOutcome,
    active_sessions,
    upsert_revive_or_add,
)

pytestmark = pytest.mark.integration

_SESSION = "1AbCintegration-session-string-account-a"
_SESSION_REMINTED = "1AbCintegration-session-string-account-a-REMINTED"
_POOL_MAX = 10


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    s = factory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()
        with db_engine.begin() as conn:
            conn.execute(text("DELETE FROM pool_sessions"))


def test_session_stored_as_ciphertext(db_engine: Engine, session: Session) -> None:
    upsert_revive_or_add(
        session, tg_user_id=900_001, session_string=_SESSION, display_label="@a", pool_max=_POOL_MAX
    )
    session.commit()

    with db_engine.connect() as conn:
        raw = conn.execute(
            text("SELECT session_string FROM pool_sessions WHERE tg_user_id = 900001")
        ).scalar()
    assert raw is not None
    assert raw != _SESSION, "plaintext session leaked into the DB!"
    assert raw.startswith("gAA"), f"DB value is not a Fernet token: {raw!r}"

    # ORM read decrypts back to plaintext.
    fresh = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)()
    try:
        active = active_sessions(fresh)
        assert any(a.session_string == _SESSION for a in active)
    finally:
        fresh.close()


def test_revive_then_add_persist(db_engine: Engine, session: Session) -> None:
    r1 = upsert_revive_or_add(
        session, tg_user_id=900_001, session_string=_SESSION, display_label="@a", pool_max=_POOL_MAX
    )
    assert r1.outcome is ReviveOutcome.ADD
    r2 = upsert_revive_or_add(
        session,
        tg_user_id=900_001,
        session_string=_SESSION_REMINTED,
        display_label="@a2",
        pool_max=_POOL_MAX,
    )
    assert r2.outcome is ReviveOutcome.REVIVE
    assert r2.previous_fingerprint == session_fingerprint(_SESSION)
    session.commit()

    count = session.execute(
        text("SELECT COUNT(*) FROM pool_sessions WHERE tg_user_id = 900001")
    ).scalar()
    assert count == 1  # revive replaced in place, no duplicate
    active = active_sessions(session)
    assert len(active) == 1
    assert active[0].session_string == _SESSION_REMINTED


def test_union_loader_merges_env_and_store(db_engine: Engine, session: Session) -> None:
    """`_union_pool_sessions` merges env + DB store, de-duped by fingerprint."""
    from collector.registry import _union_pool_sessions

    upsert_revive_or_add(
        session, tg_user_id=900_001, session_string=_SESSION, display_label="@a", pool_max=_POOL_MAX
    )
    session.commit()

    env_only = "1AbCenv-only-bootstrap-session"
    sessions, tg_user_ids, display_labels = _union_pool_sessions(
        env_sessions=[env_only, _SESSION],  # _SESSION duplicates the DB row
        fingerprint=session_fingerprint,
    )
    # DB row + the unique env session; the duplicate env _SESSION is de-duped.
    assert _SESSION in sessions
    assert env_only in sessions
    assert len(sessions) == 2
    # The DB row carries its identity + non-secret label; the env-only slot is None.
    idx_db = sessions.index(_SESSION)
    idx_env = sessions.index(env_only)
    assert tg_user_ids[idx_db] == 900_001
    assert tg_user_ids[idx_env] is None
    assert display_labels[idx_db] == "@a"  # TASK-120: DB row carries its label
    assert display_labels[idx_env] is None
