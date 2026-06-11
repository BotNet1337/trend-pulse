"""At-rest field encryption for sensitive string columns (TASK-032, Block C).

Approach: App-level Fernet symmetric encryption (cryptography library).
Chosen over pgcrypto because:
  - No DB extension required (pgcrypto is optional on managed Postgres).
  - Key stays in the application layer (env/vault); DB never sees plaintext on
    write, nor the key on read — additional defence-in-depth beyond TLS-only.
  - Portable: works with any Postgres, SQLite in tests, or a future DB.

Key management:
  - Key source: FIELD_ENCRYPTION_KEY env var (validated Fernet 32-byte urlsafe-b64).
  - Dev default: deterministic placeholder in config._DEFAULT_FIELD_ENCRYPTION_KEY.
  - Key loss: permanent data loss for encrypted columns. Store in secret manager.
  - Rotation: decrypt all rows with old key, re-encrypt with new key, deploy.

SQLAlchemy TypeDecorator `EncryptedString`:
  - `process_bind_param`: encrypt Python str → Fernet token (bytes, stored as str).
  - `process_result_value`: decrypt DB str → Python str (transparent to callers).
  - None values pass through unchanged (nullable columns stay nullable).
  - Idempotency: `try_decrypt` skips already-encrypted values (migration safety).

Decrypt-at-use: the TypeDecorator auto-decrypts when the ORM reads the column,
so `user.telegram_bot_token` always returns plaintext. No call-site changes needed
in notifier.py / delivery paths — they already read the ORM attribute.

Key resolution: the TypeDecorator resolves the key LAZILY from get_settings()
inside process_bind_param/process_result_value. get_settings() is lru_cached so
this is cheap (one Settings parse at startup, then a dict lookup per call).
This removes the need for an explicit configure() call at startup, which means
the Celery worker path works correctly without importing api.main.
"""

import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

logger = logging.getLogger(__name__)

# Sentinel prefix stored in the DB to distinguish encrypted values from
# plaintext legacy values. Fernet tokens start with "gAA" (base64-url encoded
# version byte 0x80) — using a prefix is belt-and-suspenders for the migration
# idempotency check; it is NOT a security control (the encryption is).
_FERNET_PREFIX = "gAA"


def _make_fernet(key: str) -> Fernet:
    """Construct a Fernet cipher from the base64url-encoded *key* string."""
    return Fernet(key.encode("ascii"))


def encrypt_value(plaintext: str, key: str) -> str:
    """Encrypt *plaintext* with Fernet using *key*; return the token as str.

    The returned value is a URL-safe base64 string (Fernet token), safe to
    store in a VARCHAR column. Length grows: ~89 bytes overhead + plaintext.
    """
    cipher = _make_fernet(key)
    token: bytes = cipher.encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt_value(ciphertext: str, key: str) -> str:
    """Decrypt a Fernet *ciphertext* token using *key*; return plaintext str.

    Raises `InvalidToken` (from cryptography) if the token is corrupt or the
    key is wrong. Callers should treat this as a configuration/data error.
    """
    cipher = _make_fernet(key)
    plaintext: bytes = cipher.decrypt(ciphertext.encode("ascii"))
    return plaintext.decode("utf-8")


def is_encrypted(value: str) -> bool:
    """Return True if *value* looks like a Fernet token (already encrypted).

    Used by the migration to skip values that are already encrypted
    (idempotency: running the migration twice is safe).
    """
    return value.startswith(_FERNET_PREFIX)


def _get_encryption_key() -> str:
    """Lazily resolve the field encryption key from settings (lru_cached — cheap).

    Called on every ORM bind/result operation, but get_settings() is lru_cached
    so it is effectively a dict lookup after the first call. This approach
    eliminates the need for an explicit configure() call at startup and ensures
    both the API process AND the Celery worker process resolve the key correctly
    without either importing the other's entrypoint (api/main.py vs celery_app.py).
    """
    # Deferred import to avoid circular imports at module load time
    # (storage.encryption is imported by storage.models, which is imported before
    # config is fully initialised in some test scenarios).
    from config import get_settings

    return get_settings().field_encryption_key


class EncryptedString(TypeDecorator[str]):
    """SQLAlchemy TypeDecorator that transparently encrypts/decrypts a string column.

    Usage in a model::

        from storage.encryption import EncryptedString

        class User(Base):
            telegram_bot_token: Mapped[str | None] = mapped_column(
                EncryptedString(128), nullable=True
            )

    The underlying DB column is a VARCHAR; values stored are Fernet tokens.
    The encryption key is resolved lazily from get_settings().field_encryption_key
    on each ORM operation — no explicit configure() call is required. This means
    the Celery worker path decrypts correctly without importing api.main.

    Type-checker note: `TypeDecorator[str]` declares that the Python-side type
    is `str`; `impl = String` declares the DB-side type.
    """

    impl = String
    # cache_ok=True: the type decorator has no per-instance state that affects
    # caching. The encryption key is resolved from lru_cached settings — same
    # key across all instances, so cached SQL is safe to reuse.
    # Declared as a plain attribute (not ClassVar) to match TypeDecorator's
    # instance-variable contract (mypy: ClassVar would conflict with base class).
    cache_ok: bool = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        """Encrypt on write: Python str → Fernet token stored in DB."""
        if value is None:
            return None
        key = _get_encryption_key()
        return encrypt_value(value, key)

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        """Decrypt on read: Fernet token from DB → Python str."""
        if value is None:
            return None
        key = _get_encryption_key()
        try:
            return decrypt_value(value, key)
        except InvalidToken:
            # Value in DB is not a valid Fernet token — may be a legacy plaintext
            # value (pre-migration row). Return as-is with a warning; the migration
            # should have encrypted it. This handles graceful dual-read during
            # a rolling deploy where some rows haven't been migrated yet.
            logger.warning(
                "EncryptedString: failed to decrypt value — "
                "returning as-is (possible legacy plaintext row)."
            )
            return value
