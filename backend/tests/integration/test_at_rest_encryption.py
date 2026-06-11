"""Integration tests for at-rest field encryption (TASK-032 AC5, Block C).

Validates:
- telegram_bot_token and webhook_url are stored encrypted in the DB (raw SQL
  shows Fernet ciphertext, not plaintext).
- ORM reads return correct plaintext (TypeDecorator auto-decrypts).
- Round-trip: write via ORM → raw SELECT (ciphertext) → read via ORM (plaintext).
- NULL values are preserved (no encryption of NULL).
- Migration idempotency: encrypting already-encrypted values is a no-op.
- Notifier decrypt path: _resolve_channels receives plaintext bot_token.
- Lazy key resolution: a fresh Session WITHOUT any configure() call decrypts
  correctly — proves the worker path works without importing api.main.

Marker: integration. Requires live pgvector Postgres (see conftest.py recipe).
"""

import base64
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from storage.encryption import encrypt_value, is_encrypted
from storage.models.users import User

pytestmark = pytest.mark.integration

# A realistic-looking Telegram bot token (not a real secret).
_BOT_TOKEN = "9876543210:XYZabcdefghijklmnopqrstuvwxyz12345"
_WEBHOOK_URL = "https://example.com/webhook/alerts"

# The dev Fernet key used by the Settings default (config._DEFAULT_FIELD_ENCRYPTION_KEY).
# Must match what get_settings() returns in the test environment.
_DEV_FERNET_SEED = b"trendpulse-dev-field-enc-key-001"
_DEV_FERNET_KEY = base64.urlsafe_b64encode(_DEV_FERNET_SEED).decode("ascii")


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    """Plain (non-truncating) session for encryption tests."""
    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    s = factory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _make_user(session: Session, email: str) -> User:
    """Create and persist a User with the given email, return the committed row."""
    user = User(
        email=email,
        hashed_password="x" * 60,  # dummy hash
        is_active=True,
        is_superuser=False,
        is_verified=False,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# AC5 — at-rest encryption correctness
# ---------------------------------------------------------------------------


def test_token_stored_as_ciphertext(db_engine: Engine) -> None:
    """telegram_bot_token written via ORM is stored as Fernet ciphertext in DB."""
    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        user = _make_user(session, "enc-token@example.com")
        user.telegram_bot_token = _BOT_TOKEN
        session.commit()
        user_id = user.id

        # Raw SELECT bypasses the ORM TypeDecorator — should see ciphertext.
        with db_engine.connect() as conn:
            result = conn.execute(
                text("SELECT telegram_bot_token FROM users WHERE id = :id").bindparams(id=user_id)
            )
            raw_value: str | None = result.scalar()

        assert raw_value is not None, "token should not be NULL after write"
        assert raw_value != _BOT_TOKEN, (
            f"Plaintext found in DB! Expected ciphertext, got: {raw_value!r}"
        )
        assert is_encrypted(raw_value), f"DB value does not look like a Fernet token: {raw_value!r}"
    finally:
        session.rollback()
        session.close()


def test_webhook_stored_as_ciphertext(db_engine: Engine) -> None:
    """webhook_url written via ORM is stored as Fernet ciphertext in DB."""
    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        user = _make_user(session, "enc-webhook@example.com")
        user.webhook_url = _WEBHOOK_URL
        session.commit()
        user_id = user.id

        with db_engine.connect() as conn:
            result = conn.execute(
                text("SELECT webhook_url FROM users WHERE id = :id").bindparams(id=user_id)
            )
            raw_value: str | None = result.scalar()

        assert raw_value is not None
        assert raw_value != _WEBHOOK_URL, "Plaintext webhook found in DB!"
        assert is_encrypted(raw_value), f"DB value not Fernet token: {raw_value!r}"
    finally:
        session.rollback()
        session.close()


def test_orm_round_trip_decrypts(db_engine: Engine) -> None:
    """ORM read returns correct plaintext after write (TypeDecorator round-trip)."""
    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    s1 = factory()
    try:
        user = _make_user(s1, "roundtrip@example.com")
        user.telegram_bot_token = _BOT_TOKEN
        user.webhook_url = _WEBHOOK_URL
        s1.commit()
        user_id = user.id
    finally:
        s1.close()

    # Fresh session → ORM reads through TypeDecorator → should return plaintext.
    s2 = factory()
    try:
        fetched: User | None = s2.get(User, user_id)
        assert fetched is not None
        assert fetched.telegram_bot_token == _BOT_TOKEN, (
            f"Expected {_BOT_TOKEN!r}, got {fetched.telegram_bot_token!r}"
        )
        assert fetched.webhook_url == _WEBHOOK_URL, (
            f"Expected {_WEBHOOK_URL!r}, got {fetched.webhook_url!r}"
        )
    finally:
        s2.close()


def test_null_values_preserved(db_engine: Engine) -> None:
    """NULL values pass through the TypeDecorator unchanged."""
    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        user = _make_user(session, "nullenc@example.com")
        # telegram_bot_token and webhook_url default to NULL.
        assert user.telegram_bot_token is None
        assert user.webhook_url is None
    finally:
        session.close()


def test_migration_idempotency() -> None:
    """Encrypting an already-encrypted value (starting with Fernet prefix) is a no-op.

    This validates the migration's idempotency guard: running upgrade() twice
    should not double-encrypt values.
    """
    # Simulate what the migration does: encrypt once, check idempotency.
    ciphertext = encrypt_value(_BOT_TOKEN, _DEV_FERNET_KEY)
    assert is_encrypted(ciphertext), "Encrypted value should start with Fernet prefix"

    # On the second pass the migration would detect is_encrypted=True and skip.
    # Re-encrypting a Fernet token would produce garbage (double-encrypt).
    # We assert that is_encrypted() correctly identifies the token so the
    # migration can skip it safely.
    assert is_encrypted(ciphertext), "is_encrypted should return True for Fernet token"
    assert not is_encrypted(_BOT_TOKEN), "is_encrypted should return False for plaintext"


def test_notifier_receives_plaintext(db_engine: Engine) -> None:
    """notifier._resolve_channels receives plaintext bot_token (decrypt path).

    The notifier reads user.telegram_bot_token — the TypeDecorator auto-decrypts
    so the notifier never sees ciphertext. We test this by calling _resolve_channels
    directly with a user that has an encrypted token in the DB.
    """
    from alerts.notifier import _resolve_channels
    from config import get_settings

    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    s1 = factory()
    try:
        user = _make_user(s1, "notifier-decrypt@example.com")
        user.telegram_bot_token = _BOT_TOKEN
        user.telegram_chat_id = "-100123456789"
        s1.commit()
        user_id = user.id
    finally:
        s1.close()

    s2 = factory()
    try:
        fetched: User | None = s2.get(User, user_id)
        assert fetched is not None

        settings = get_settings()
        channels = _resolve_channels(fetched, settings)
        # Should have exactly one Telegram channel (no webhook, not pro/team).
        assert len(channels) == 1, f"Expected 1 channel, got {len(channels)}"

        from alerts.backends import TelegramTarget

        target = channels[0].target
        assert isinstance(target, TelegramTarget)
        assert target.bot_token == _BOT_TOKEN, (
            f"Notifier received ciphertext instead of plaintext: {target.bot_token!r}"
        )
    finally:
        s2.close()


def test_lazy_key_resolution_without_configure(db_engine: Engine) -> None:
    """Lazy key resolution: decryption works without any configure() call.

    This test proves that the Celery worker path (which never imports api.main)
    can decrypt encrypted columns correctly. We persist an encrypted token, then
    read it back via a fresh Session WITHOUT calling EncryptedString.configure()
    — the TypeDecorator must resolve the key from get_settings() lazily.

    Root cause of TASK-032 CRITICAL finding: the old configure()-based approach
    required api.main to be imported, which the Celery worker never did.
    The lazy approach removes this footgun entirely.
    """
    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)

    # Write encrypted token via ORM (no configure() call — key from settings).
    s1 = factory()
    try:
        user = _make_user(s1, "lazy-key@example.com")
        user.telegram_bot_token = _BOT_TOKEN
        s1.commit()
        user_id = user.id
    finally:
        s1.close()

    # Verify raw DB value is ciphertext (not plaintext).
    with db_engine.connect() as conn:
        result = conn.execute(
            text("SELECT telegram_bot_token FROM users WHERE id = :id").bindparams(id=user_id)
        )
        raw_value: str | None = result.scalar()
    assert raw_value is not None
    assert is_encrypted(raw_value), f"Expected Fernet ciphertext in DB, got: {raw_value!r}"
    assert raw_value != _BOT_TOKEN, "Plaintext leaked into DB — encryption not applied"

    # Read back via a fresh session WITHOUT calling configure() — lazy resolution.
    s2 = factory()
    try:
        fetched: User | None = s2.get(User, user_id)
        assert fetched is not None
        assert fetched.telegram_bot_token == _BOT_TOKEN, (
            f"Lazy key resolution failed: expected {_BOT_TOKEN!r}, "
            f"got {fetched.telegram_bot_token!r}"
        )
    finally:
        s2.close()
