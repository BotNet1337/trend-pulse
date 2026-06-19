"""Typed service over the `factory_accounts` table — create/transition/list (TASK-132).

The account-factory store: persist an account the factory is provisioning, drive it
through the validated state machine (`factory.constants.ALLOWED_TRANSITIONS`), expose
the rows by state for the factory loop, and sum the provisioning cost for budgeting.

Security invariants (ADR-008 / CONVENTIONS):
  * `session_string` is ENCRYPTED at rest via the model's `EncryptedString` column; it
    is NEVER logged. The DTO that carries it is `repr=False` on the secret field so a
    stray `repr()` / log line / traceback frame cannot echo it. The `proxy` (carries
    user:pass creds) gets the same treatment.
  * `phone_masked` is stored masked only — the full phone is never persisted; the store
    has no API to pass a full number (the parameter is named `phone_masked`).
  * State transitions are logged WITHOUT secrets (no session string, no full phone) —
    only the account id + from/to state.

The store operates on a caller-provided `Session` (unit-of-work owned by the caller /
`storage.database.get_session`) and is the ONLY writer of `factory_accounts`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from factory.constants import (
    ALLOWED_TRANSITIONS,
    FACTORY_PHONE_MASK_CHAR,
    FACTORY_STATE_PURCHASED,
)
from factory.errors import (
    FactoryAccountNotFoundError,
    FactoryAccountValidationError,
    IllegalFactoryTransitionError,
)
from storage.models.base import utcnow
from storage.models.factory_accounts import FactoryAccount

logger = logging.getLogger(__name__)

# Coalesce target for an empty `cost_usd` sum — Decimal zero, never None or float.
_ZERO_USD = Decimal("0")


@dataclass(frozen=True)
class FactoryAccountRecord:
    """A persisted factory account (carries secrets — repr-suppressed on those fields).

    `session_string` (the plaintext Telethon StringSession, decrypted by the
    EncryptedString TypeDecorator on read) and `proxy` (a SOCKS5 URI carrying
    user:pass creds) are repr-suppressed so a stray `repr()`/log/traceback cannot
    echo them. They are None until the account is `registered` / when no proxy is set.
    """

    id: int
    phone_masked: str
    provider: str
    provider_order_id: str
    tg_user_id: int | None
    state: str
    probation_until: datetime | None
    cost_usd: Decimal
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    # repr=False: the session is a secret — keep it out of any repr()/log/traceback.
    session_string: str | None = field(default=None, repr=False)
    # repr=False: the proxy carries user:pass creds — same secret treatment.
    proxy: str | None = field(default=None, repr=False)


def _to_record(row: FactoryAccount) -> FactoryAccountRecord:
    """Map an ORM row to the immutable DTO (decrypts session/proxy via the TypeDecorator)."""
    return FactoryAccountRecord(
        id=row.id,
        phone_masked=row.phone_masked,
        provider=row.provider,
        provider_order_id=row.provider_order_id,
        tg_user_id=row.tg_user_id,
        state=row.state,
        probation_until=row.probation_until,
        cost_usd=row.cost_usd,
        last_error=row.last_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
        session_string=row.session_string,
        proxy=row.proxy,
    )


def create_purchased(
    session: Session,
    *,
    phone_masked: str,
    provider: str,
    provider_order_id: str,
    cost_usd: Decimal,
    proxy: str | None = None,
) -> FactoryAccountRecord:
    """Insert a new account in state `purchased`; flush; return the record.

    `phone_masked` is a MASKED phone (e.g. `+79*****1234`) — the store never accepts a
    full number. As a defence-in-depth guard, a value that contains no mask char is
    rejected with `FactoryAccountValidationError` (the value itself is PII and is never
    echoed in the message). `session_string`/`tg_user_id` are NULL at this stage (set
    later on the `registered` transition). `proxy`, if given, is encrypted at rest.
    """
    if FACTORY_PHONE_MASK_CHAR not in phone_masked:
        raise FactoryAccountValidationError(
            f"phone_masked must be masked (contain {FACTORY_PHONE_MASK_CHAR!r})"
        )
    now = utcnow()
    row = FactoryAccount(
        phone_masked=phone_masked,
        provider=provider,
        provider_order_id=provider_order_id,
        proxy=proxy,
        state=FACTORY_STATE_PURCHASED,
        cost_usd=cost_usd,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    logger.info(
        "factory account purchased",
        extra={"account_id": row.id, "provider": provider, "state": FACTORY_STATE_PURCHASED},
    )
    return _to_record(row)


def transition(
    session: Session,
    account_id: int,
    to_state: str,
    *,
    session_string: str | None = None,
    tg_user_id: int | None = None,
    probation_until: datetime | None = None,
    last_error: str | None = None,
) -> FactoryAccountRecord:
    """Move an account to `to_state`, validating against `ALLOWED_TRANSITIONS`.

    Loads the row (raise `FactoryAccountNotFoundError` if absent), checks that
    `to_state` is in `ALLOWED_TRANSITIONS[current_state]` (else raise
    `IllegalFactoryTransitionError`), then applies the new state plus any provided
    optional fields: `session_string`/`tg_user_id` (set on the `registered` move),
    `probation_until` (set on the `probation` move), `last_error` (set on
    `failed`/`banned`). Bumps `updated_at`, flushes, and returns the record. Only
    explicitly-provided optional fields are written (None means "leave unchanged").
    """
    row = session.scalars(
        select(FactoryAccount).where(FactoryAccount.id == account_id)
    ).one_or_none()
    if row is None:
        raise FactoryAccountNotFoundError(f"no factory account with id {account_id}")

    from_state = row.state
    if to_state not in ALLOWED_TRANSITIONS.get(from_state, frozenset()):
        raise IllegalFactoryTransitionError(
            f"illegal factory transition {from_state!r} -> {to_state!r} (account_id {account_id})"
        )

    row.state = to_state
    if session_string is not None:
        row.session_string = session_string
    if tg_user_id is not None:
        row.tg_user_id = tg_user_id
    if probation_until is not None:
        row.probation_until = probation_until
    if last_error is not None:
        row.last_error = last_error
    row.updated_at = utcnow()
    session.flush()
    logger.info(
        "factory account transition",
        extra={"account_id": account_id, "from_state": from_state, "to_state": to_state},
    )
    return _to_record(row)


def get(session: Session, account_id: int) -> FactoryAccountRecord | None:
    """Return the account record for `account_id`, or None if no such row."""
    row = session.scalars(
        select(FactoryAccount).where(FactoryAccount.id == account_id)
    ).one_or_none()
    if row is None:
        return None
    return _to_record(row)


def list_by_state(session: Session, state: str) -> list[FactoryAccountRecord]:
    """Return all accounts in `state`, ordered by id for a stable listing."""
    rows = session.scalars(
        select(FactoryAccount).where(FactoryAccount.state == state).order_by(FactoryAccount.id)
    ).all()
    return [_to_record(row) for row in rows]


def total_spent_usd(session: Session) -> Decimal:
    """Sum `cost_usd` across ALL factory accounts (Decimal; empty table → Decimal('0'))."""
    total = session.scalar(select(func.coalesce(func.sum(FactoryAccount.cost_usd), _ZERO_USD)))
    if total is None:
        return _ZERO_USD
    return Decimal(total)
