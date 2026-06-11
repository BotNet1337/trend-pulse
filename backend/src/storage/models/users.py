"""`users` — tenant root and the fastapi-users user table.

This is the SINGLE `User` model for the whole app. It is the tenant root (every
user-owned table FKs `user_id -> users.id ON DELETE CASCADE`, task-002) AND the
fastapi-users user table: it mixes in `SQLAlchemyBaseUserTable[int]`, which adds
`email` (unique), `hashed_password`, `is_active`, `is_superuser`, `is_verified`.

The id stays an **integer** PK (`FastAPIUsers[User, int]`) — switching to UUID
would break every existing `user_id` FK. The mixin is a plain `Generic[ID]`
(not a `DeclarativeBase`), so it composes with our `Base` without a metaclass
clash. `email` is declared by the mixin only (no double definition).
"""

from datetime import datetime

from fastapi_users_db_sqlalchemy import (
    SQLAlchemyBaseOAuthAccountTable,
    SQLAlchemyBaseUserTable,
)
from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from storage.encryption import EncryptedString
from storage.models.base import Base, utcnow

# Plan tiers (task-009 gating seam; hard enforcement is task-010). Telegram is
# available on every plan; webhook delivery requires `pro` or `team`. Named, not
# magic literals (CONVENTIONS).
PLAN_FREE = "free"
PLAN_PRO = "pro"
PLAN_TEAM = "team"
_PLAN_MAX = 16
# Column widths for the (secret) delivery-config fields (TASK-032 at-rest encryption).
# Fernet encryption adds ~89 bytes overhead to each value. The stored ciphertext is a
# base64url-encoded token: overhead ≈ 89 + ceil(plaintext_len / 16) * 16 bytes.
# Widths are padded generously beyond the plaintext max to fit encrypted values.
# _TELEGRAM_BOT_TOKEN_MAX: token is up to 128 chars plaintext → 300 encrypted.
# _TELEGRAM_CHAT_ID_MAX: chat id is up to 64 chars plaintext → 250 encrypted.
# _WEBHOOK_URL_MAX: webhook URL up to 2048 chars → 2300 encrypted.
# The DB column type is VARCHAR; the TypeDecorator stores Fernet tokens as ASCII strings.
_TELEGRAM_BOT_TOKEN_MAX = 300  # was 128 (plaintext); now 300 for encrypted Fernet token
_TELEGRAM_CHAT_ID_MAX = 64  # chat_id is NOT encrypted (not a secret: it's a channel id)
_WEBHOOK_URL_MAX = 2300  # was 2048 (plaintext); now 2300 for encrypted Fernet token
# Referral ref_code: short URL-safe token, generous upper bound (TASK-046).
_REF_CODE_MAX = 32


class OAuthAccount(SQLAlchemyBaseOAuthAccountTable[int], Base):
    """Linked third-party (Google) identity for a user — fastapi-users OAuth table.

    Integer PK + integer `user_id` FK into `users` with `ON DELETE CASCADE`,
    consistent with the rest of the schema (account deletion removes linked
    OAuth accounts). The base mixin supplies `oauth_name`, `access_token`,
    `expires_at`, `refresh_token`, `account_id`, `account_email`.
    """

    __tablename__ = "oauth_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )


class User(SQLAlchemyBaseUserTable[int], Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    # `lazy="joined"` is required by fastapi-users so the OAuth router can read a
    # user's linked accounts in one query; `passive_deletes` defers row removal to
    # the DB-level CASCADE above (no per-row ORM delete).
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(
        OAuthAccount, lazy="joined", passive_deletes=True
    )
    # --- Delivery config (task-009). All additive/nullable/defaulted (migration
    # 0004), so existing rows are backward-compatible.
    # TASK-032: telegram_bot_token and webhook_url are encrypted at rest using
    # EncryptedString (Fernet). The ORM transparently encrypts on write and
    # decrypts on read — callers (notifier.py) always receive plaintext.
    # telegram_chat_id is NOT encrypted: it is a Telegram channel/chat ID
    # (public information, not a secret — unlike the bot token or webhook URL).
    # Column widths are enlarged to accommodate Fernet ciphertext overhead. ---
    telegram_bot_token: Mapped[str | None] = mapped_column(
        EncryptedString(_TELEGRAM_BOT_TOKEN_MAX), nullable=True
    )
    telegram_chat_id: Mapped[str | None] = mapped_column(
        String(_TELEGRAM_CHAT_ID_MAX), nullable=True
    )
    webhook_url: Mapped[str | None] = mapped_column(
        EncryptedString(_WEBHOOK_URL_MAX), nullable=True
    )
    # Plan gating seam (task-009): webhook delivery requires pro/team. Hard plan
    # enforcement is task-010; this column is the membership check.
    plan: Mapped[str] = mapped_column(
        String(_PLAN_MAX), nullable=False, server_default=PLAN_FREE, default=PLAN_FREE
    )
    # Referral program (TASK-046). Both fields are nullable and additive.
    # ref_code: unique share code; NULL until first GET /referral/me (lazy generation).
    # referred_by: FK to users.id of the referrer; set once at registration, never updated.
    # ON DELETE SET NULL: if referrer is deleted, referred_by is cleared (GDPR-safe).
    ref_code: Mapped[str | None] = mapped_column(
        String(_REF_CODE_MAX),
        nullable=True,
        unique=True,
        default=None,
    )
    referred_by: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
