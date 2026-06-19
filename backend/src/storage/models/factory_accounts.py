"""`factory_accounts` — provisioning lifecycle for technical accounts (TASK-132, B3).

Each row is ONE account the factory is provisioning through a state machine
(`purchased → registered → probation → promoted`, with `failed`/`banned` off-ramps).
This is the factory's OWN source-of-truth, SEPARATE from `pool_sessions`: an account
is held on probation here BEFORE it ever enters the live pool — promotion COPIES the
session into `pool_sessions` (see `storage.pool_session_store.upsert_revive_or_add`).

Secret/PII handling (ADR-008 / CONVENTIONS):
  * `session_string` (the Telethon StringSession, set after registration) is stored in
    an `EncryptedString` column — a Fernet token at rest, NEVER plaintext, NEVER logged.
  * `proxy` (a SOCKS5 URI carrying user:pass creds) is likewise `EncryptedString`.
  * `phone_masked` stores ONLY a masked number (e.g. `+79*****1234`) — the full phone is
    NEVER persisted after registration (compliance + minimise secret surface).

Column widths are named constants (CONVENTIONS: no magic literals).
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from factory.constants import (
    FACTORY_LAST_ERROR_MAX,
    FACTORY_PHONE_MASKED_MAX,
    FACTORY_PROVIDER_MAX,
    FACTORY_PROVIDER_ORDER_ID_MAX,
    FACTORY_PROXY_MAX,
    FACTORY_SESSION_STRING_MAX,
    FACTORY_STATE_MAX,
)
from storage.encryption import EncryptedString
from storage.models.base import Base, utcnow

# `cost_usd` precision: USD amounts with cent precision; 10 integer+fraction digits is
# ample for a per-account provisioning cost (named constants, no magic literals).
_COST_PRECISION = 10
_COST_SCALE = 2


class FactoryAccount(Base):
    """One factory-provisioned account: lifecycle state + encrypted session + masked phone.

    `state`: one of `factory.constants.FACTORY_STATES`; transitions are validated by the
             store against `ALLOWED_TRANSITIONS` (the store is the only writer).
    `phone_masked`: a MASKED phone (e.g. `+79*****1234`) — the full number is never stored.
    `session_string`/`tg_user_id`: NULL until the account is `registered`; the session is
             ENCRYPTED at rest (Fernet TypeDecorator) and never logged.
    `proxy`: optional SOCKS5 URI carrying creds → ENCRYPTED like `session_string`.
    `probation_until`: when the warming/probation window ends (set on the probation move).
    `cost_usd`: the provisioning cost of this account — summed for budget accounting.
    `last_error`: a non-secret diagnostic recorded on a `failed`/`banned` transition.
    """

    __tablename__ = "factory_accounts"
    __table_args__ = (
        Index("ix_factory_accounts_state", "state"),
        Index("ix_factory_accounts_probation_until", "probation_until"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Masked phone only (e.g. `+79*****1234`) — the full number is NEVER persisted.
    phone_masked: Mapped[str] = mapped_column(
        String(FACTORY_PHONE_MASKED_MAX),
        nullable=False,
    )
    # Provider slug (e.g. `sms-activate`) — non-secret.
    provider: Mapped[str] = mapped_column(
        String(FACTORY_PROVIDER_MAX),
        nullable=False,
    )
    # The provider's order/activation id — opaque upstream token (non-secret).
    provider_order_id: Mapped[str] = mapped_column(
        String(FACTORY_PROVIDER_ORDER_ID_MAX),
        nullable=False,
    )
    # SOCKS5 proxy URI — carries user:pass creds → ENCRYPTED, NEVER logged. NULL = none.
    proxy: Mapped[str | None] = mapped_column(
        EncryptedString(FACTORY_PROXY_MAX),
        nullable=True,
        default=None,
    )
    # The Telegram account identity (get_me().id) — set after registration. NULL before.
    tg_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        default=None,
    )
    # The Telethon StringSession — ENCRYPTED at rest (Fernet). NULL until registration.
    session_string: Mapped[str | None] = mapped_column(
        EncryptedString(FACTORY_SESSION_STRING_MAX),
        nullable=True,
        default=None,
    )
    # Lifecycle state — one of FACTORY_STATES; transitions validated by the store.
    state: Mapped[str] = mapped_column(
        String(FACTORY_STATE_MAX),
        nullable=False,
    )
    # When the probation/warming window ends (set on the probation transition). NULL else.
    probation_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    # The provisioning cost of this account (USD) — summed for budget accounting.
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(_COST_PRECISION, _COST_SCALE),
        nullable=False,
    )
    # A non-secret diagnostic recorded on a failed/banned transition. NULL when none.
    last_error: Mapped[str | None] = mapped_column(
        String(FACTORY_LAST_ERROR_MAX),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )
