"""`pool_sessions` — dynamic, QR-minted technical-account sessions (TASK-119).

Each row is ONE technical Telegram account, keyed by its Telegram account identity
(`tg_user_id` from `client.get_me()` after a successful QR login). The minted
StringSession is stored in an `EncryptedString` column (ADR-008 Fernet
TypeDecorator) — encrypted at rest, NEVER plaintext, NEVER logged, NEVER in Redis.

The worker pool loads from the union of env `TELEGRAM_POOL_SESSIONS` and the active
rows of this table (see `storage.pool_session_store`); re-scanning a QR for an
account already present REVIVES the same row in place (replace session + clear
`revoked_at`) instead of inserting a duplicate.

Non-secret identifiers stored alongside the secret:
  * `session_fingerprint` — sha256[:16] (TASK-102), the persistent-quarantine key,
    used to clear the OLD fingerprint's quarantine on a revive.
  * `display_label` — masked id / `@username` from `get_me()` for the UI.

Column widths are named constants (CONVENTIONS: no magic literals).
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from collector.constants import (
    POOL_SESSION_DISPLAY_LABEL_MAX,
    POOL_SESSION_PROXY_MAX,
    POOL_SESSION_STRING_MAX,
    POOL_SOURCE_MANUAL,
    POOL_SOURCE_MAX,
)
from collector.constants import SESSION_FINGERPRINT_LEN as _FINGERPRINT_LEN
from storage.encryption import EncryptedString
from storage.models.base import Base, utcnow


class PoolSession(Base):
    """One dynamic pool technical account: encrypted session + non-secret identity.

    `tg_user_id`: the Telegram account identity (from `get_me()`), UNIQUE — the
                  upsert key that distinguishes a REVIVE (row exists) from an ADD.
    `session_string`: the Telethon StringSession, ENCRYPTED at rest (ADR-008). The
                  underlying DB column is a VARCHAR holding a Fernet token — the
                  plaintext is never written, logged, or placed in Redis.
    `session_fingerprint`: non-secret sha256[:16] (TASK-102) for quarantine clearing.
    `display_label`: non-secret masked id / `@username` for the UI.
    `revoked_at`: soft-revoke timestamp; NULL means active. Rows are kept for audit
                  (mirrors `api_keys` / `subscriptions`). The active loader filters
                  `revoked_at IS NULL`.
    """

    __tablename__ = "pool_sessions"
    __table_args__ = (Index("ix_pool_sessions_revoked_at", "revoked_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # The Telegram account identity (get_me().id) — a 64-bit id. UNIQUE + indexed:
    # one row per account, fast revive-vs-add lookup. NEVER a secret.
    tg_user_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        unique=True,
        index=True,
    )
    # The StringSession — ENCRYPTED at rest (Fernet TypeDecorator). The Python-side
    # value is the plaintext session; the DB-side value is a Fernet token.
    session_string: Mapped[str] = mapped_column(
        EncryptedString(POOL_SESSION_STRING_MAX),
        nullable=False,
    )
    # Non-secret sha256[:16] of the session (TASK-102) — the persistent-quarantine key.
    session_fingerprint: Mapped[str] = mapped_column(
        String(_FINGERPRINT_LEN),
        nullable=False,
    )
    # Non-secret masked id / @username for the UI (from get_me()).
    display_label: Mapped[str] = mapped_column(
        String(POOL_SESSION_DISPLAY_LABEL_MAX),
        nullable=False,
    )
    # SOCKS5 proxy URI for this session (TASK-129). Non-secret? NO — it carries
    # user:pass credentials → ENCRYPTED like session_string via EncryptedString,
    # NEVER logged, NEVER placed in Redis, NEVER sent via the API. NULL means no
    # proxy configured for this slot (behaviour is byte-identical to today).
    proxy: Mapped[str | None] = mapped_column(
        EncryptedString(POOL_SESSION_PROXY_MAX),
        nullable=True,
        default=None,
    )
    # Non-secret provenance (TASK-130): `manual` (owner via QR) vs `auto` (account-factory,
    # TASK-134). Default `manual`; `server_default` backfills existing rows. Surfaced in the
    # health snapshot + pool-admin UI badge — never a secret.
    source: Mapped[str] = mapped_column(
        String(POOL_SOURCE_MAX),
        nullable=False,
        server_default=POOL_SOURCE_MANUAL,
        default=POOL_SOURCE_MANUAL,
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
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
