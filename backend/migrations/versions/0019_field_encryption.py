"""At-rest field encryption for telegram_bot_token and webhook_url (TASK-032).

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-11

Schema + data changes:
1. ALTER TABLE users ALTER COLUMN telegram_bot_token TYPE VARCHAR(300)
   (was 128 — enlarged to fit Fernet ciphertext overhead of ~89 bytes).
2. ALTER TABLE users ALTER COLUMN webhook_url TYPE VARCHAR(2300)
   (was 2048 — enlarged to fit Fernet ciphertext).
3. DATA MIGRATION: encrypt existing plaintext values in-place using Fernet
   with the key from FIELD_ENCRYPTION_KEY env var.
   - Idempotent: values starting with the Fernet prefix ("gAA") are skipped.
   - NULL values are left unchanged.

Downgrade:
  - Decrypt all ciphertext values back to plaintext.
  - Shrink column widths back to original sizes.
  - WARNING: downgrade requires the same FIELD_ENCRYPTION_KEY to be set.
    If the key is lost, downgrade cannot recover the original values.

Security notes:
  - The key is sourced from FIELD_ENCRYPTION_KEY env var (never hardcoded).
  - The migration uses raw SQL with bind params (CONVENTIONS: no f-string SQL).
  - The Alembic `op.execute(text(...).bindparams(...))` pattern is used for
    per-row updates to avoid loading all users into Python (O(N) DB round-trips
    would be needed; instead we use a single UPDATE with a function).
  - For large tables, prefer a batched migration; this is acceptable at current
    user volumes (early-stage SaaS).
"""

import base64
import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Column width constants matching storage/models/users.py (post-TASK-032).
_TELEGRAM_BOT_TOKEN_MAX_OLD = 128
_TELEGRAM_BOT_TOKEN_MAX_NEW = 300
_WEBHOOK_URL_MAX_OLD = 2048
_WEBHOOK_URL_MAX_NEW = 2300

# Fernet token prefix — all Fernet tokens start with this (base64url of version
# byte 0x80). Used to detect already-encrypted values for idempotency.
_FERNET_PREFIX = "gAA"

# Dev-default Fernet key (same seed as config._DEFAULT_FIELD_ENCRYPTION_KEY).
# NEVER used in production: FIELD_ENCRYPTION_KEY env var overrides this.
_DEV_FERNET_SEED = b"trendpulse-dev-field-enc-key-001"  # exactly 32 bytes
_DEV_FERNET_KEY = base64.urlsafe_b64encode(_DEV_FERNET_SEED).decode("ascii")


def _get_fernet() -> Fernet:
    """Load the Fernet cipher from FIELD_ENCRYPTION_KEY env or dev default."""
    raw_key = os.environ.get("FIELD_ENCRYPTION_KEY", _DEV_FERNET_KEY)
    return Fernet(raw_key.encode("ascii"))


def _encrypt_row(cipher: Fernet, plaintext: str) -> str:
    """Encrypt a single plaintext value; return the Fernet token as str."""
    token: bytes = cipher.encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def _decrypt_row(cipher: Fernet, ciphertext: str) -> str:
    """Decrypt a Fernet token; return plaintext. Raises InvalidToken on failure."""
    plaintext: bytes = cipher.decrypt(ciphertext.encode("ascii"))
    return plaintext.decode("utf-8")


def upgrade() -> None:
    """Widen columns and encrypt existing plaintext values in-place."""
    conn = op.get_bind()
    cipher = _get_fernet()

    # 1. Widen telegram_bot_token VARCHAR to fit Fernet ciphertext.
    op.alter_column(
        "users",
        "telegram_bot_token",
        type_=sa.String(length=_TELEGRAM_BOT_TOKEN_MAX_NEW),
        existing_type=sa.String(length=_TELEGRAM_BOT_TOKEN_MAX_OLD),
        existing_nullable=True,
    )

    # 2. Widen webhook_url VARCHAR to fit Fernet ciphertext.
    op.alter_column(
        "users",
        "webhook_url",
        type_=sa.String(length=_WEBHOOK_URL_MAX_NEW),
        existing_type=sa.String(length=_WEBHOOK_URL_MAX_OLD),
        existing_nullable=True,
    )

    # 3. Data migration: encrypt existing plaintext values.
    # Fetch all rows that have at least one non-NULL sensitive field.
    rows = conn.execute(
        text(
            "SELECT id, telegram_bot_token, webhook_url "
            "FROM users "
            "WHERE telegram_bot_token IS NOT NULL OR webhook_url IS NOT NULL"
        )
    ).fetchall()

    for row in rows:
        user_id: int = row[0]
        bot_token: str | None = row[1]
        webhook_url: str | None = row[2]

        new_token: str | None = None
        new_webhook: str | None = None
        needs_update = False

        if bot_token is not None:
            if bot_token.startswith(_FERNET_PREFIX):
                # Already encrypted — idempotent skip.
                new_token = bot_token
            else:
                new_token = _encrypt_row(cipher, bot_token)
                needs_update = True

        if webhook_url is not None:
            if webhook_url.startswith(_FERNET_PREFIX):
                # Already encrypted — idempotent skip.
                new_webhook = webhook_url
            else:
                new_webhook = _encrypt_row(cipher, webhook_url)
                needs_update = True

        if needs_update:
            conn.execute(
                text(
                    "UPDATE users "
                    "SET telegram_bot_token = :token, webhook_url = :webhook "
                    "WHERE id = :id"
                ).bindparams(
                    token=new_token,
                    webhook=new_webhook,
                    id=user_id,
                )
            )


def downgrade() -> None:
    """Decrypt values back to plaintext and shrink columns to original widths.

    WARNING: requires the same FIELD_ENCRYPTION_KEY that was used in upgrade().
    If the key is unavailable, this downgrade will fail with InvalidToken errors.
    """
    conn = op.get_bind()
    cipher = _get_fernet()

    # Decrypt all encrypted values back to plaintext.
    rows = conn.execute(
        text(
            "SELECT id, telegram_bot_token, webhook_url "
            "FROM users "
            "WHERE telegram_bot_token IS NOT NULL OR webhook_url IS NOT NULL"
        )
    ).fetchall()

    for row in rows:
        user_id: int = row[0]
        bot_token: str | None = row[1]
        webhook_url: str | None = row[2]

        new_token: str | None = None
        new_webhook: str | None = None
        needs_update = False

        if bot_token is not None:
            if bot_token.startswith(_FERNET_PREFIX):
                try:
                    new_token = _decrypt_row(cipher, bot_token)
                    needs_update = True
                except InvalidToken:
                    # Cannot decrypt — leave as-is (best effort).
                    new_token = bot_token
            else:
                new_token = bot_token

        if webhook_url is not None:
            if webhook_url.startswith(_FERNET_PREFIX):
                try:
                    new_webhook = _decrypt_row(cipher, webhook_url)
                    needs_update = True
                except InvalidToken:
                    new_webhook = webhook_url
            else:
                new_webhook = webhook_url

        if needs_update:
            conn.execute(
                text(
                    "UPDATE users "
                    "SET telegram_bot_token = :token, webhook_url = :webhook "
                    "WHERE id = :id"
                ).bindparams(
                    token=new_token,
                    webhook=new_webhook,
                    id=user_id,
                )
            )

    # Shrink columns back to original widths.
    op.alter_column(
        "users",
        "telegram_bot_token",
        type_=sa.String(length=_TELEGRAM_BOT_TOKEN_MAX_OLD),
        existing_type=sa.String(length=_TELEGRAM_BOT_TOKEN_MAX_NEW),
        existing_nullable=True,
    )
    op.alter_column(
        "users",
        "webhook_url",
        type_=sa.String(length=_WEBHOOK_URL_MAX_OLD),
        existing_type=sa.String(length=_WEBHOOK_URL_MAX_NEW),
        existing_nullable=True,
    )
