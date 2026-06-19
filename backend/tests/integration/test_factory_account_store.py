"""TASK-132 — factory account store integration (encrypted at rest on real Postgres).

Validates against a live pgvector Postgres (see conftest.py recipe):
  * a `session_string` set on a `registered` transition is stored as Fernet ciphertext
    (raw SELECT != plaintext, startswith `gAA`), while the ORM read returns plaintext.
  * `total_spent_usd` sums `cost_usd` across rows on real Postgres NUMERIC.

Marker: integration. Requires live pgvector Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from factory.constants import FACTORY_STATE_REGISTERED
from storage.factory_account_store import (
    create_purchased,
    get,
    total_spent_usd,
    transition,
)

pytestmark = pytest.mark.integration

_PHONE_MASKED = "+79*****1234"
_PROVIDER = "sms-activate"
_ORDER_ID = "order-int-123"
_SESSION = "1AbCintegration-factory-session-string"


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
            conn.execute(text("DELETE FROM factory_accounts"))


def test_session_stored_as_ciphertext(db_engine: Engine, session: Session) -> None:
    record = create_purchased(
        session,
        phone_masked=_PHONE_MASKED,
        provider=_PROVIDER,
        provider_order_id=_ORDER_ID,
        cost_usd=Decimal("1.50"),
    )
    transition(
        session,
        record.id,
        FACTORY_STATE_REGISTERED,
        session_string=_SESSION,
        tg_user_id=900_101,
    )
    session.commit()

    with db_engine.connect() as conn:
        raw = conn.execute(
            text("SELECT session_string FROM factory_accounts WHERE id = :id"),
            {"id": record.id},
        ).scalar()
    assert raw is not None
    assert raw != _SESSION, "plaintext session leaked into the DB!"
    assert raw.startswith("gAA"), f"DB value is not a Fernet token: {raw!r}"

    # ORM read decrypts back to plaintext.
    fresh = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)()
    try:
        fetched = get(fresh, record.id)
        assert fetched is not None
        assert fetched.session_string == _SESSION
    finally:
        fresh.close()


def test_total_spent_usd_sums_on_postgres(db_engine: Engine, session: Session) -> None:
    create_purchased(
        session,
        phone_masked=_PHONE_MASKED,
        provider=_PROVIDER,
        provider_order_id=_ORDER_ID,
        cost_usd=Decimal("1.50"),
    )
    create_purchased(
        session,
        phone_masked=_PHONE_MASKED,
        provider=_PROVIDER,
        provider_order_id=_ORDER_ID,
        cost_usd=Decimal("2.25"),
    )
    session.commit()
    assert total_spent_usd(session) == Decimal("3.75")
