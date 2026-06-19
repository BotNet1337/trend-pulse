"""TASK-132 — factory_accounts store (state machine, masked phone, encrypted session).

Exercises the store against an in-memory SQLite (the `EncryptedString` TypeDecorator
works over SQLite VARCHAR — the at-rest-ciphertext assertion against a real Postgres
column lives in the integration test). Covers:
  * create_purchased inserts a row in state `purchased` (session/tg_user_id NULL).
  * the session set on a `registered` transition is ENCRYPTED at rest.
  * the legal path purchased→registered→probation→promoted persists state.
  * an illegal transition (purchased→promoted, registered→promoted) raises.
  * a transition on an unknown id raises FactoryAccountNotFoundError.
  * list_by_state returns only matching rows, ordered by id.
  * total_spent_usd sums cost_usd across rows (and is Decimal("0") on an empty table).
  * the phone is stored masked only; the DTO repr hides the session secret.
  * the transition map is consistent (every state keyed, terminals empty, etc).
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import StaticPool, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from factory.constants import (
    ALLOWED_TRANSITIONS,
    FACTORY_STATE_BANNED,
    FACTORY_STATE_FAILED,
    FACTORY_STATE_PROBATION,
    FACTORY_STATE_PROMOTED,
    FACTORY_STATE_PURCHASED,
    FACTORY_STATE_REGISTERED,
    FACTORY_STATES,
)
from factory.errors import (
    FactoryAccountNotFoundError,
    FactoryAccountValidationError,
    IllegalFactoryTransitionError,
)
from storage.factory_account_store import (
    FactoryAccountRecord,
    create_purchased,
    get,
    list_by_state,
    total_spent_usd,
    transition,
)
from storage.models.base import Base

_PHONE_MASKED = "+79*****1234"
_PROVIDER = "sms-activate"
_ORDER_ID = "order-abc-123"
_COST = Decimal("1.50")
_SESSION = "1AbCsession-factory-account-xyz"


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


def _create(db: Session, *, cost: Decimal = _COST) -> FactoryAccountRecord:
    return create_purchased(
        db,
        phone_masked=_PHONE_MASKED,
        provider=_PROVIDER,
        provider_order_id=_ORDER_ID,
        cost_usd=cost,
    )


def test_create_purchased_inserts_row_in_purchased_state(db: Session) -> None:
    record = _create(db)
    assert record.state == FACTORY_STATE_PURCHASED
    assert record.phone_masked == _PHONE_MASKED
    assert record.provider == _PROVIDER
    assert record.provider_order_id == _ORDER_ID
    assert record.cost_usd == _COST
    assert record.session_string is None
    assert record.tg_user_id is None
    # get returns the same row.
    fetched = get(db, record.id)
    assert fetched is not None
    assert fetched.id == record.id
    assert fetched.state == FACTORY_STATE_PURCHASED


def test_session_is_encrypted_at_rest(db: Session) -> None:
    """A `session_string` set on a `registered` transition is a Fernet token at rest."""
    record = _create(db)
    transition(
        db,
        record.id,
        FACTORY_STATE_REGISTERED,
        session_string=_SESSION,
        tg_user_id=555,
    )
    db.commit()
    raw = db.execute(
        text("SELECT session_string FROM factory_accounts WHERE id = :id"),
        {"id": record.id},
    ).scalar()
    assert raw is not None
    assert raw != _SESSION, "plaintext session leaked into the DB column"
    assert raw.startswith("gAA"), "DB column is not a Fernet ciphertext token"
    # ORM read decrypts back.
    fetched = get(db, record.id)
    assert fetched is not None
    assert fetched.session_string == _SESSION
    assert fetched.tg_user_id == 555


def test_legal_full_path_succeeds_and_persists(db: Session) -> None:
    record = _create(db)
    r1 = transition(db, record.id, FACTORY_STATE_REGISTERED, session_string=_SESSION, tg_user_id=1)
    assert r1.state == FACTORY_STATE_REGISTERED
    r2 = transition(db, record.id, FACTORY_STATE_PROBATION)
    assert r2.state == FACTORY_STATE_PROBATION
    r3 = transition(db, record.id, FACTORY_STATE_PROMOTED)
    assert r3.state == FACTORY_STATE_PROMOTED
    # Persisted.
    fetched = get(db, record.id)
    assert fetched is not None
    assert fetched.state == FACTORY_STATE_PROMOTED


def test_illegal_transition_purchased_to_promoted_raises(db: Session) -> None:
    record = _create(db)
    with pytest.raises(IllegalFactoryTransitionError):
        transition(db, record.id, FACTORY_STATE_PROMOTED)


def test_purchased_to_banned_is_legal_and_persists(db: Session) -> None:
    """A slot can be banned/flagged by the SMS provider (e.g. VoIP) before registration."""
    record = _create(db)
    result = transition(db, record.id, FACTORY_STATE_BANNED, last_error="provider flagged VoIP")
    assert result.state == FACTORY_STATE_BANNED
    fetched = get(db, record.id)
    assert fetched is not None
    assert fetched.state == FACTORY_STATE_BANNED


def test_illegal_transition_purchased_to_probation_raises(db: Session) -> None:
    record = _create(db)
    with pytest.raises(IllegalFactoryTransitionError):
        transition(db, record.id, FACTORY_STATE_PROBATION)


def test_illegal_transition_registered_to_promoted_raises(db: Session) -> None:
    record = _create(db)
    transition(db, record.id, FACTORY_STATE_REGISTERED, session_string=_SESSION, tg_user_id=1)
    with pytest.raises(IllegalFactoryTransitionError):
        transition(db, record.id, FACTORY_STATE_PROMOTED)


def test_transition_unknown_id_raises(db: Session) -> None:
    with pytest.raises(FactoryAccountNotFoundError):
        transition(db, 999_999, FACTORY_STATE_REGISTERED)


def test_list_by_state_returns_only_matching_ordered_by_id(db: Session) -> None:
    a = _create(db)
    b = _create(db)
    c = _create(db)
    # Move b to registered.
    transition(db, b.id, FACTORY_STATE_REGISTERED, session_string=_SESSION, tg_user_id=1)
    purchased = list_by_state(db, FACTORY_STATE_PURCHASED)
    assert [r.id for r in purchased] == [a.id, c.id]
    registered = list_by_state(db, FACTORY_STATE_REGISTERED)
    assert [r.id for r in registered] == [b.id]


def test_total_spent_usd_sums_cost(db: Session) -> None:
    assert total_spent_usd(db) == Decimal("0")
    _create(db, cost=Decimal("1.50"))
    _create(db, cost=Decimal("2.25"))
    assert total_spent_usd(db) == Decimal("3.75")


def test_phone_stored_masked_only(db: Session) -> None:
    record = create_purchased(
        db,
        phone_masked="+79*****1234",
        provider=_PROVIDER,
        provider_order_id=_ORDER_ID,
        cost_usd=_COST,
    )
    stored = db.execute(
        text("SELECT phone_masked FROM factory_accounts WHERE id = :id"),
        {"id": record.id},
    ).scalar()
    assert stored == "+79*****1234"


def test_create_purchased_rejects_unmasked_phone(db: Session) -> None:
    """A full (unmasked) phone — no `*` — is rejected before it can be persisted (PII)."""
    with pytest.raises(FactoryAccountValidationError):
        create_purchased(
            db,
            phone_masked="+79991234567",
            provider=_PROVIDER,
            provider_order_id=_ORDER_ID,
            cost_usd=_COST,
        )


def test_dto_repr_hides_session_secret(db: Session) -> None:
    record = _create(db)
    transition(db, record.id, FACTORY_STATE_REGISTERED, session_string=_SESSION, tg_user_id=1)
    fetched = get(db, record.id)
    assert fetched is not None
    assert _SESSION not in repr(fetched)
    assert fetched.session_string == _SESSION  # still accessible


def test_dto_repr_hides_proxy_secret(db: Session) -> None:
    """The proxy carries user:pass creds (repr=False) — repr must not echo it."""
    proxy = "socks5://user:secretpass@host:1080"
    record = create_purchased(
        db,
        phone_masked=_PHONE_MASKED,
        provider=_PROVIDER,
        provider_order_id=_ORDER_ID,
        cost_usd=_COST,
        proxy=proxy,
    )
    transition(db, record.id, FACTORY_STATE_REGISTERED, session_string=_SESSION, tg_user_id=1)
    for fetched in (get(db, record.id), *list_by_state(db, FACTORY_STATE_REGISTERED)):
        assert fetched is not None
        assert "secretpass" not in repr(fetched)
        assert "socks5://" not in repr(fetched)
        assert _SESSION not in repr(fetched)
        assert fetched.proxy == proxy  # still accessible


def test_last_error_recorded_on_failed_transition(db: Session) -> None:
    record = _create(db)
    result = transition(db, record.id, FACTORY_STATE_FAILED, last_error="sms code never arrived")
    assert result.state == FACTORY_STATE_FAILED
    assert result.last_error == "sms code never arrived"


# --- transition-map consistency (constants) ---


def test_every_state_is_a_transition_key() -> None:
    for state in FACTORY_STATES:
        assert state in ALLOWED_TRANSITIONS


def test_terminal_states_have_no_outgoing_transitions() -> None:
    for terminal in (FACTORY_STATE_PROMOTED, FACTORY_STATE_FAILED, FACTORY_STATE_BANNED):
        assert ALLOWED_TRANSITIONS[terminal] == frozenset()


def test_promoted_reachable_only_from_probation() -> None:
    sources = {
        state for state, nexts in ALLOWED_TRANSITIONS.items() if FACTORY_STATE_PROMOTED in nexts
    }
    assert sources == {FACTORY_STATE_PROBATION}


def test_transition_targets_are_known_states() -> None:
    for nexts in ALLOWED_TRANSITIONS.values():
        for nxt in nexts:
            assert nxt in FACTORY_STATES
