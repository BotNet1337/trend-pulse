"""`api_keys` — hashed API-key records for Team-plan programmatic access (TASK-028).

Only `key_hash` (SHA-256 hex) and `prefix` (leading characters for display /
narrow-lookup) are stored. The plaintext key is returned exactly once on creation
and is NEVER persisted or logged (security invariant — CONVENTIONS).

Column widths are named constants (no magic literals, CONVENTIONS).
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from storage.models.base import Base, utcnow

# Column widths — named constants (CONVENTIONS: no magic literals).
_NAME_MAX = 255
_KEY_HASH_LEN = 64  # SHA-256 hex digest: 32 bytes → 64 hex chars
_PREFIX_MAX = 32  # generous upper bound for the stored prefix


class ApiKey(Base):
    """A Team-plan API key: only the hash + prefix are at-rest, not the plaintext.

    `key_hash`: SHA-256 hex of the full plaintext key (unique, indexed for lookup).
    `prefix`:   Leading N characters of the plaintext key (indexed for narrow-lookup
                before constant-time compare; also shown in list/masked responses).
    `revoked_at`: Soft-revoke timestamp; NULL means active. Rows are kept for audit.
    `last_used_at`: Updated on each successful resolve (nullable, auth-path update).
    """

    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_api_keys_prefix", "prefix"),
        Index("ix_api_keys_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The SHA-256 hex digest (64 chars). Unique + indexed — one key_hash per row,
    # fast exact-match lookup after prefix narrowing.
    key_hash: Mapped[str] = mapped_column(
        String(_KEY_HASH_LEN),
        nullable=False,
        unique=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(_NAME_MAX), nullable=False)
    # Leading N chars stored separately for narrow-lookup + display (avoids
    # scanning all rows on every auth request).
    prefix: Mapped[str] = mapped_column(String(_PREFIX_MAX), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
