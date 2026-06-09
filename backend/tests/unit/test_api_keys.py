"""Unit tests for API-keys feature (TASK-028).

Covers:
- Key generation: format (tp_ prefix), entropy (non-deterministic), hash ≠ plaintext,
  prefix is leading substring of plaintext.
- Constant-time resolve: valid key → User; invalid plaintext → None; revoked → None;
  compare_digest path confirmed (mocked session).
- Masking: ApiKeyRead schema contains no key/key_hash fields; present fields correct.
- Revoke: soft-revoke sets revoked_at; foreign/missing key → False.
- Downgrade-gate: Free effective_plan → resolve returns None (key disabled after downgrade).

Mocks the SQLAlchemy session where needed so no DB is required (unit tests).
"""

import hashlib
import secrets
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from api.api_keys.constants import _PREFIX_LEN, API_KEY_PREFIX
from api.api_keys.schemas import ApiKeyCreated, ApiKeyRead
from api.api_keys.service import (
    create_api_key,
    generate_api_key,
    list_api_keys,
    resolve_api_key,
    revoke_api_key,
)

# ─── generate_api_key ─────────────────────────────────────────────────────────


def test_generate_key_starts_with_brand_prefix() -> None:
    plaintext, _hash, _prefix = generate_api_key()
    assert plaintext.startswith(API_KEY_PREFIX), f"key must start with {API_KEY_PREFIX!r}"


def test_generate_key_hash_is_sha256_hex() -> None:
    plaintext, key_hash, _ = generate_api_key()
    expected = hashlib.sha256(plaintext.encode()).hexdigest()
    assert key_hash == expected, "key_hash must be SHA-256 of plaintext"
    assert len(key_hash) == 64, "SHA-256 hex = 64 chars"


def test_generate_key_hash_not_equal_plaintext() -> None:
    plaintext, key_hash, _ = generate_api_key()
    assert key_hash != plaintext, "key_hash must NOT be the plaintext"


def test_generate_key_prefix_is_leading_substring() -> None:
    plaintext, _, prefix = generate_api_key()
    expected_prefix = plaintext[: len(API_KEY_PREFIX) + _PREFIX_LEN]
    assert prefix == expected_prefix, "prefix must be the leading N chars of plaintext"
    assert plaintext.startswith(prefix), "prefix must be a prefix of plaintext"


def test_generate_key_has_sufficient_entropy() -> None:
    """Two separately generated keys must differ (probabilistic; 1-(1/2^256) certainty)."""
    pt1, _, _ = generate_api_key()
    pt2, _, _ = generate_api_key()
    assert pt1 != pt2, "keys must be unique (secrets.token_urlsafe)"


def test_generate_key_plaintext_length_is_reasonable() -> None:
    """Plaintext = 'tp_' + token_urlsafe(32) — expected ~46 chars (3 + ~43)."""
    plaintext, _, _ = generate_api_key()
    # token_urlsafe(32) → ceil(32*4/3) = 44 chars (url-safe base64, no padding)
    # Allow some slack for base64 variants.
    assert len(plaintext) > len(API_KEY_PREFIX) + 30, "key must be long enough for entropy"


# ─── create_api_key ───────────────────────────────────────────────────────────


def _mock_session_add() -> MagicMock:
    """Return a mock session that records add/flush calls and returns a flushed id."""
    session = MagicMock()

    def _flush_side_effect() -> None:
        # Simulate autoincrement id assignment after flush
        for call_args in session.add.call_args_list:
            row = call_args[0][0]
            if not hasattr(row, "id") or row.id is None:
                row.id = 1

    session.flush.side_effect = _flush_side_effect
    return session


def test_create_api_key_returns_row_and_plaintext() -> None:
    session = _mock_session_add()
    # Give the row an id on flush
    created_rows: list[object] = []

    def _track_add(obj: object) -> None:
        created_rows.append(obj)

    session.add.side_effect = _track_add

    def _flush() -> None:
        for row in created_rows:
            if not hasattr(row, "id") or row.id is None:
                object.__setattr__(row, "id", 42)

    session.flush.side_effect = _flush

    row, plaintext = create_api_key(session, user_id=7, name="test-key")
    assert row.user_id == 7
    assert row.name == "test-key"
    assert row.key_hash != plaintext, "key_hash must not be plaintext"
    assert plaintext.startswith(API_KEY_PREFIX)
    assert len(row.key_hash) == 64
    # Verify DB row doesn't have a 'key' attribute (plaintext not stored)
    assert not hasattr(row, "key"), "plaintext must not be stored in the row"


# ─── resolve_api_key (constant-time, valid/invalid/revoked) ───────────────────


def _make_api_key_row(*, plaintext: str, user_id: int = 1, revoked: bool = False) -> MagicMock:
    """Build a mock ApiKey row matching the given plaintext."""
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    prefix = plaintext[: len(API_KEY_PREFIX) + _PREFIX_LEN]
    row = MagicMock()
    row.key_hash = key_hash
    row.prefix = prefix
    row.user_id = user_id
    row.revoked_at = datetime.now(UTC) if revoked else None
    row.last_used_at = None
    return row


def _make_user_row(*, user_id: int = 1, plan: str = "team") -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.plan = plan
    return user


def test_resolve_valid_key_returns_user() -> None:
    """Valid plaintext key with active Team plan → returns User."""
    plaintext, _, _ = generate_api_key()
    api_key_row = _make_api_key_row(plaintext=plaintext, user_id=5)
    user = _make_user_row(user_id=5, plan="team")

    session = MagicMock()
    session.scalars.return_value.all.return_value = [api_key_row]
    session.get.return_value = user

    with patch("api.api_keys.service.assert_within_limit") as mock_gate:
        mock_gate.return_value = None  # Team: API_ACCESS available → gate does not raise

        result = resolve_api_key(session, plaintext)
    assert result is not None
    assert result.id == user.id


def test_resolve_invalid_key_returns_none() -> None:
    """Wrong/random plaintext → no candidate match → None."""
    session = MagicMock()
    session.scalars.return_value.all.return_value = []  # no candidates

    result = resolve_api_key(session, "tp_completely_wrong_key_that_matches_nothing")
    assert result is None


def test_resolve_revoked_key_returns_none() -> None:
    """Revoked key (revoked_at set) is excluded by the WHERE clause → no candidates → None."""
    plaintext, _, _ = generate_api_key()
    # The query filters revoked_at IS NULL, so revoked rows won't be in candidates.
    # Simulate by returning empty list (as the DB query would).
    session = MagicMock()
    session.scalars.return_value.all.return_value = []

    result = resolve_api_key(session, plaintext)
    assert result is None


def test_resolve_uses_compare_digest() -> None:
    """Verify secrets.compare_digest is called (constant-time) in the resolve path."""
    plaintext, _, _ = generate_api_key()
    api_key_row = _make_api_key_row(plaintext=plaintext)
    user = _make_user_row(plan="team")

    session = MagicMock()
    session.scalars.return_value.all.return_value = [api_key_row]
    session.get.return_value = user

    with (
        patch("secrets.compare_digest", wraps=secrets.compare_digest) as mock_cd,
        patch("api.api_keys.service.assert_within_limit") as mock_gate,
    ):
        mock_gate.return_value = None  # Team: gate does not raise

        resolve_api_key(session, plaintext)

    mock_cd.assert_called_once()
    # Both args passed to compare_digest are 64-char SHA-256 hex digests (not plaintext).
    call_args = mock_cd.call_args[0]
    assert len(call_args[0]) == 64 and len(call_args[1]) == 64


def test_resolve_wrong_candidate_hash_returns_none() -> None:
    """A candidate with a mismatched hash (wrong key) must NOT authenticate."""
    plaintext, _, _ = generate_api_key()
    other_pt, _, _ = generate_api_key()
    # Row exists for prefix but different plaintext → hashes differ
    fake_row = _make_api_key_row(plaintext=other_pt)
    # Override prefix to match our plaintext (simulate collision)
    fake_row.prefix = plaintext[: len(API_KEY_PREFIX) + _PREFIX_LEN]

    session = MagicMock()
    session.scalars.return_value.all.return_value = [fake_row]

    result = resolve_api_key(session, plaintext)
    assert result is None, "mismatched hash candidate must not authenticate"


# ─── downgrade-gate ───────────────────────────────────────────────────────────


def test_resolve_downgrade_gate_free_returns_none() -> None:
    """After downgrade to Free, the key's effective plan lacks API_ACCESS → None."""
    plaintext, _, _ = generate_api_key()
    api_key_row = _make_api_key_row(plaintext=plaintext)
    user = _make_user_row(plan="free")

    session = MagicMock()
    session.scalars.return_value.all.return_value = [api_key_row]
    session.get.return_value = user

    with patch("api.api_keys.service.assert_within_limit") as mock_gate:
        from billing.limits import PlanLimitExceeded

        # Free plan lacks API_ACCESS → the billing gate raises → resolve returns None.
        mock_gate.side_effect = PlanLimitExceeded("api_access not on free plan", code=403)

        result = resolve_api_key(session, plaintext)

    assert result is None, "downgraded-to-Free user must not authenticate via API key"


# ─── revoke_api_key ───────────────────────────────────────────────────────────


def test_revoke_own_key_returns_true_and_sets_revoked_at() -> None:
    """Revoking own key → True + revoked_at set (soft-revoke)."""
    row = MagicMock()
    row.id = 10
    row.user_id = 3
    row.revoked_at = None

    session = MagicMock()
    session.get.return_value = row

    result = revoke_api_key(session, user_id=3, key_id=10)
    assert result is True
    assert row.revoked_at is not None
    session.flush.assert_called_once()


def test_revoke_nonexistent_key_returns_false() -> None:
    session = MagicMock()
    session.get.return_value = None
    result = revoke_api_key(session, user_id=1, key_id=999)
    assert result is False


def test_revoke_foreign_key_returns_false() -> None:
    """Attempting to revoke another user's key → False (no side effects)."""
    row = MagicMock()
    row.id = 5
    row.user_id = 99  # belongs to user 99

    session = MagicMock()
    session.get.return_value = row

    result = revoke_api_key(session, user_id=1, key_id=5)  # user 1 tries to revoke
    assert result is False
    # No side effects: a foreign key is never flushed/modified.
    session.flush.assert_not_called()


# ─── list_api_keys ────────────────────────────────────────────────────────────


def test_list_api_keys_returns_own_keys() -> None:
    row1 = MagicMock()
    row2 = MagicMock()
    session = MagicMock()
    session.scalars.return_value.all.return_value = [row1, row2]

    result = list_api_keys(session, user_id=7)
    assert len(result) == 2


# ─── Schema masking ───────────────────────────────────────────────────────────


def test_api_key_read_schema_has_no_key_field() -> None:
    """ApiKeyRead must not expose 'key' or 'key_hash' fields."""
    fields = ApiKeyRead.model_fields
    assert "key" not in fields, "ApiKeyRead must not have 'key' field"
    assert "key_hash" not in fields, "ApiKeyRead must not have 'key_hash' field"


def test_api_key_read_schema_has_expected_fields() -> None:
    expected = {"id", "name", "prefix", "created_at", "last_used_at", "revoked_at"}
    assert set(ApiKeyRead.model_fields.keys()) == expected


def test_api_key_created_schema_has_key_field() -> None:
    """ApiKeyCreated must contain the 'key' (plaintext) field — it's the creation response."""
    assert "key" in ApiKeyCreated.model_fields


def test_api_key_read_validates_from_attributes() -> None:
    """ApiKeyRead can be built from an ORM-like object (from_attributes=True)."""
    now = datetime.now(UTC)
    obj = SimpleNamespace(
        id=1,
        name="test",
        prefix="tp_abcdef",
        created_at=now,
        last_used_at=None,
        revoked_at=None,
    )
    read = ApiKeyRead.model_validate(obj)
    assert read.id == 1
    assert read.name == "test"
    assert read.prefix == "tp_abcdef"
    assert read.last_used_at is None
    assert read.revoked_at is None
