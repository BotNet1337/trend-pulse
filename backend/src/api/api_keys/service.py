"""API-key service — generate, store (hash-only), list, revoke, and resolve.

Security invariants (TASK-028 / CONVENTIONS):
- Plaintext is NEVER stored or logged. Only key_hash (SHA-256 hex) is persisted.
- Resolve uses secrets.compare_digest for constant-time comparison (no timing leak).
- `resolve_api_key` gates on effective_plan(API_ACCESS): a downgraded user whose
  key was issued on Team gets None after downgrade (conservative, documented below).
- All errors are explicit; full type hints throughout.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.api_keys.constants import (
    _LAST_USED_THROTTLE_SECONDS,
    _PREFIX_LEN,
    _TOKEN_NBYTES,
    API_KEY_PREFIX,
)
from billing.limits import PlanLimitExceeded, assert_within_limit
from billing.plans import Resource
from storage.models.api_keys import ApiKey
from storage.models.users import User


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key triple: (plaintext, key_hash, prefix).

    - `plaintext` = ``tp_<url-safe-random>``  (returned once to the caller, never stored)
    - `key_hash`  = SHA-256 hex of plaintext   (stored in DB, used for verification)
    - `prefix`    = leading ``len(API_KEY_PREFIX) + _PREFIX_LEN`` chars of plaintext
                    (stored for narrow-lookup + display)

    Entropy: secrets.token_urlsafe(32) → 43 URL-safe chars → 256-bit security.
    """
    secret = secrets.token_urlsafe(_TOKEN_NBYTES)
    plaintext = f"{API_KEY_PREFIX}{secret}"
    prefix = plaintext[: len(API_KEY_PREFIX) + _PREFIX_LEN]
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    return plaintext, key_hash, prefix


def create_api_key(session: Session, *, user_id: int, name: str) -> tuple[ApiKey, str]:
    """Create and persist a new API key for `user_id`.

    Returns ``(ApiKey row, plaintext)``. The plaintext is NOT stored in the DB —
    the caller must return it to the user exactly once and discard it.
    """
    plaintext, key_hash, prefix = generate_api_key()
    row = ApiKey(
        user_id=user_id,
        key_hash=key_hash,
        prefix=prefix,
        name=name,
    )
    session.add(row)
    session.flush()
    # Plaintext is never assigned to the row — only the caller holds it briefly.
    return row, plaintext


def list_api_keys(session: Session, *, user_id: int) -> list[ApiKey]:
    """Return all (including revoked) API keys owned by `user_id`.

    Revoked keys are included so the user can see the audit trail. The router
    response schema (`ApiKeyRead`) omits key/key_hash — only prefix + metadata.
    """
    stmt = select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.created_at.desc())
    return list(session.scalars(stmt).all())


def revoke_api_key(session: Session, *, user_id: int, key_id: int) -> bool:
    """Soft-revoke `key_id` owned by `user_id`: set revoked_at = utcnow().

    Returns True on success, False if the key does not exist or belongs to
    another user (router maps False → 404 without leaking existence).
    """
    row = session.get(ApiKey, key_id)
    if row is None or row.user_id != user_id:
        return False
    row.revoked_at = datetime.now(UTC)
    session.flush()
    return True


def resolve_api_key(session: Session, plaintext: str) -> User | None:
    """Resolve a plaintext API key to the owning User, or None if invalid/revoked.

    Algorithm:
    1. Compute SHA-256 of plaintext.
    2. Extract prefix (same formula as generate_api_key).
    3. Narrow the query to non-revoked rows matching the prefix.
    4. For each candidate: **constant-time** compare via secrets.compare_digest
       (prevents timing attacks — prefix is NOT sufficient for auth).
    5. On match: check effective_plan → API_ACCESS; if not active → None
       (downgrade-gate: after Team → Free downgrade the key stops working).
    6. Update last_used_at; return User.

    Security notes:
    - Never log or return plaintext or key_hash.
    - compare_digest is always called (no early-exit on prefix alone).
    - Downgrade-gate uses effective_plan (billing/limits.py — not user.plan directly)
      so an expired subscription also revokes API access.
    """
    computed_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    prefix = plaintext[: len(API_KEY_PREFIX) + _PREFIX_LEN]

    stmt = select(ApiKey).where(ApiKey.prefix == prefix, ApiKey.revoked_at.is_(None))
    candidates = list(session.scalars(stmt).all())

    matched: ApiKey | None = None
    for candidate in candidates:
        # constant-time compare — MUST NOT short-circuit on prefix match
        if secrets.compare_digest(candidate.key_hash, computed_hash):
            matched = candidate
            break

    if matched is None:
        return None

    user = session.get(User, matched.user_id)
    if user is None:
        return None

    # Downgrade-gate via the SINGLE billing source of truth (no parallel plan
    # logic). API_ACCESS is a FEATURE resource, so assert_within_limit raises
    # PlanLimitExceeded when the current effective plan lacks it — after a
    # Team → Free downgrade (or an expired subscription) the key stops resolving.
    try:
        assert_within_limit(session, user, Resource.API_ACCESS)
    except PlanLimitExceeded:
        return None

    # Throttle last_used_at writes: programmatic clients hit read endpoints at high
    # RPS, and updating the same row every request causes write-amplification and
    # row contention. Coarse (per-_LAST_USED_THROTTLE_SECONDS) tracking is enough.
    now = datetime.now(UTC)
    if matched.last_used_at is None or (now - matched.last_used_at) >= timedelta(
        seconds=_LAST_USED_THROTTLE_SECONDS
    ):
        matched.last_used_at = now
        session.flush()

    return user
