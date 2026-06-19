"""Typed service over the `pool_sessions` table — upsert/active/quarantine (TASK-119).

The dynamic pool session store: persist a QR-minted session keyed by the Telegram
account identity (`tg_user_id`), decide REVIVE vs ADD, expose the active sessions to
the worker pool loader, and coordinate clearing the persisted quarantine on a revive.

Security invariants (ADR-008 / ADR-dynamic-pool-session-store / CONVENTIONS):
  * The session string is ENCRYPTED at rest via the model's `EncryptedString` column;
    it is NEVER logged. The DTOs that carry it are `repr=False` on the secret field so
    a stray `repr()` / log line / traceback frame cannot echo it.
  * Only the worker loader receives the plaintext session (to build a Telethon client);
    the non-secret identifiers (`tg_user_id`, `session_fingerprint`, `display_label`)
    are the only things ever surfaced to the API / UI / Redis.
  * The session string NEVER travels through Redis — Redis carries only the non-secret
    revive-signal + the existing non-secret quarantine fingerprints (TASK-102).

The store operates on a caller-provided `Session` (unit-of-work owned by the caller /
`storage.database.get_session`), mirroring the repository/service layer.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, cast

from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session

from collector.constants import (
    POOL_SOURCE_MANUAL,
    QUARANTINE_REDIS_KEY,
    SESSION_FINGERPRINT_LEN,
)
from collector.errors import PoolCapacityExceededError
from collector.telegram.account_pool import session_fingerprint
from storage.models.base import utcnow
from storage.models.pool_sessions import PoolSession

if TYPE_CHECKING:
    from redis import Redis

logger = logging.getLogger(__name__)


class ReviveOutcome(Enum):
    """Whether an upsert REVIVED an existing account or ADDED a new one (TASK-119)."""

    REVIVE = "revive"
    ADD = "add"


@dataclass(frozen=True)
class StoredSession:
    """A persisted pool session handed to the worker loader (carries the secret).

    `session_string` is the plaintext Telethon StringSession — repr-suppressed so a
    stray `repr()`/log line cannot echo it. Only the worker (building a real client)
    ever reads it; the API/UI use `tg_user_id`/`fingerprint`/`display_label`.

    `proxy` (TASK-129) is the plaintext SOCKS5 proxy URI (decrypted by the
    EncryptedString TypeDecorator on DB read), or None when no proxy is configured.
    It carries user:pass credentials → repr-suppressed like `session_string`,
    NEVER logged, NEVER placed in Redis, NEVER sent via the API.
    """

    tg_user_id: int
    fingerprint: str
    display_label: str
    # repr=False: the session is a secret — keep it out of any repr()/log/traceback.
    session_string: str = field(default="", repr=False)
    # repr=False: the proxy carries user:pass creds — same secret treatment as session.
    proxy: str | None = field(default=None, repr=False)
    # Non-secret provenance (TASK-130): `manual` (owner via QR) vs `auto` (factory). NOT
    # repr-suppressed — it is not a secret. Default `manual`.
    source: str = POOL_SOURCE_MANUAL


@dataclass(frozen=True)
class UpsertResult:
    """The outcome of `upsert_revive_or_add` — non-secret identity + REVIVE/ADD.

    Carries NO session string: the caller (the revive API, TASK-120) needs only the
    non-secret identity to write the revive-signal and the outcome to render the UI.
    """

    outcome: ReviveOutcome
    tg_user_id: int
    fingerprint: str
    display_label: str
    # The OLD fingerprint that was replaced on a REVIVE (None on an ADD) — the caller
    # clears its persisted quarantine so the revived slot is not reloaded as dead.
    previous_fingerprint: str | None = None


def upsert_revive_or_add(
    session: Session,
    *,
    tg_user_id: int,
    session_string: str,
    display_label: str,
    pool_max: int,
    env_floor_size: int = 0,
    source: str | None = None,
) -> UpsertResult:
    """Persist a minted session keyed by `tg_user_id`: REVIVE if it exists, else ADD.

    REVIVE (a row already exists for `tg_user_id`): replace `session_string` +
    `session_fingerprint`, refresh `display_label`/`updated_at`, and clear `revoked_at`
    — the same row, no duplicate. Returns the OLD fingerprint as `previous_fingerprint`
    so the caller can clear its persisted quarantine.

    ADD (no row for `tg_user_id`): insert — but only if the active row count is below the
    EFFECTIVE cap `pool_max - env_floor_size`; otherwise raise `PoolCapacityExceededError`
    (the API maps it to a 4xx). `env_floor_size` (TASK-119 fix) is the count of distinct
    env `TELEGRAM_POOL_SESSIONS` slots that the worker also unions into the pool — the ADD
    cap MUST reserve room for them so active DB rows + env can never exceed `POOL_MAX` and
    crash `from_sessions`. Default 0 keeps the bare DB-only cap for callers that do not
    union an env floor. A revive of an existing account never trips the cap (it replaces
    in place). The effective cap is floored at 0 so a misconfigured env floor larger than
    `pool_max` rejects every ADD rather than going negative.

    The fingerprint is derived from the session via `session_fingerprint` (sha256[:16],
    non-secret). The session string is written through the model's `EncryptedString`
    column (encrypted at rest); it is never logged here.

    `source` (TASK-130) is the non-secret provenance written on the row: `manual` (the
    owner onboarded it via QR) or `auto` (the account-factory promotion, TASK-134).
    When None (the default — QR callers pass no value), an ADD records `manual` and a
    REVIVE PRESERVES the existing row's provenance (a QR re-mint of an auto-promoted
    account must NOT silently demote it to `manual`). An explicit non-None `source`
    (the factory) is written on both an ADD and a REVIVE so a promotion can set/flip it.
    """
    fingerprint = session_fingerprint(session_string)
    existing = session.scalars(
        select(PoolSession).where(PoolSession.tg_user_id == tg_user_id)
    ).one_or_none()

    now = utcnow()
    if existing is not None:
        previous_fingerprint = existing.session_fingerprint
        existing.session_string = session_string
        existing.session_fingerprint = fingerprint
        existing.display_label = display_label
        # Preserve existing provenance on a QR revive (source=None); only an explicit
        # non-None source (the factory promotion) overwrites it (TASK-130 review fix).
        if source is not None:
            existing.source = source
        existing.revoked_at = None
        existing.updated_at = now
        session.flush()
        logger.info(
            "pool session revived",
            extra={"tg_user_id": tg_user_id, "fingerprint": fingerprint},
        )
        return UpsertResult(
            outcome=ReviveOutcome.REVIVE,
            tg_user_id=tg_user_id,
            fingerprint=fingerprint,
            display_label=display_label,
            previous_fingerprint=previous_fingerprint,
        )

    active = _active_count(session)
    effective_cap = max(0, pool_max - env_floor_size)
    if active >= effective_cap:
        raise PoolCapacityExceededError(
            f"cannot add pool account: {active} active DB sessions at the effective cap "
            f"{effective_cap} (POOL_MAX={pool_max} - env_floor={env_floor_size})"
        )
    row = PoolSession(
        tg_user_id=tg_user_id,
        session_string=session_string,
        session_fingerprint=fingerprint,
        display_label=display_label,
        # source=None (QR add) records `manual`; an explicit value (factory) is kept.
        source=source if source is not None else POOL_SOURCE_MANUAL,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    logger.info(
        "pool session added",
        extra={"tg_user_id": tg_user_id, "fingerprint": fingerprint},
    )
    return UpsertResult(
        outcome=ReviveOutcome.ADD,
        tg_user_id=tg_user_id,
        fingerprint=fingerprint,
        display_label=display_label,
        previous_fingerprint=None,
    )


def active_sessions(session: Session) -> list[StoredSession]:
    """Return all ACTIVE (not soft-revoked) stored sessions for the worker loader.

    Each `StoredSession` carries the decrypted plaintext session (read through the
    `EncryptedString` TypeDecorator) — only the worker building Telethon clients calls
    this. Ordered by `tg_user_id` for a stable pool layout across restarts.
    """
    rows = session.scalars(
        select(PoolSession).where(PoolSession.revoked_at.is_(None)).order_by(PoolSession.tg_user_id)
    ).all()
    return [
        StoredSession(
            tg_user_id=row.tg_user_id,
            fingerprint=row.session_fingerprint,
            display_label=row.display_label,
            session_string=row.session_string,
            proxy=row.proxy,
            source=row.source,
        )
        for row in rows
    ]


def find_active_by_tg_user_id(session: Session, tg_user_id: int) -> StoredSession | None:
    """Return the ACTIVE stored session for `tg_user_id` (the worker revive lookup).

    Used by the worker when it applies a revive-signal: it loads the NEW session for
    exactly the targeted slot from the encrypted store (the secret never came via
    Redis). Returns None if no active row exists (e.g. revoked between signal + tick).
    """
    row = session.scalars(
        select(PoolSession).where(
            PoolSession.tg_user_id == tg_user_id,
            PoolSession.revoked_at.is_(None),
        )
    ).one_or_none()
    if row is None:
        return None
    return StoredSession(
        tg_user_id=row.tg_user_id,
        fingerprint=row.session_fingerprint,
        display_label=row.display_label,
        session_string=row.session_string,
        proxy=row.proxy,
        source=row.source,
    )


def revoke(session: Session, *, tg_user_id: int) -> bool:
    """Soft-revoke the account for `tg_user_id` (set `revoked_at`). Idempotent.

    Returns True if a row was found (and is now revoked), False if no such row. Keeps
    the row for audit (mirrors `api_keys`); the active loader filters it out.
    """
    row = session.scalars(
        select(PoolSession).where(PoolSession.tg_user_id == tg_user_id)
    ).one_or_none()
    if row is None:
        return False
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        session.flush()
    return True


def clear_quarantine_for(redis: "Redis | None", fingerprint: str) -> None:
    """Remove a fingerprint from the persisted quarantine set (TASK-102) on revive.

    Best-effort, fail-open: a Redis error logs a warning and is swallowed (mirrors
    `AccountPool._persist_quarantine`). Removing the OLD fingerprint means the next
    pool build / load does not re-mark the revived account dead. A None/empty
    fingerprint or `redis=None` is a no-op. NEVER handles a session string.
    """
    if redis is None or not _is_valid_fingerprint(fingerprint):
        return
    try:
        cast("int", redis.srem(QUARANTINE_REDIS_KEY, fingerprint))
    except RedisError:
        logger.warning("could not clear session quarantine on revive (Redis); ignoring")


def _active_count(session: Session) -> int:
    """Count ACTIVE (not soft-revoked) rows — the cap check for an ADD."""
    return len(
        session.scalars(select(PoolSession.id).where(PoolSession.revoked_at.is_(None))).all()
    )


def _is_valid_fingerprint(value: str) -> bool:
    """A well-formed fingerprint: exactly SESSION_FINGERPRINT_LEN lowercase hex chars.

    Mirrors `account_pool._is_valid_fingerprint` — defense-in-depth so a malformed
    value can never be sent to Redis as a member to remove.
    """
    return len(value) == SESSION_FINGERPRINT_LEN and all(c in "0123456789abcdef" for c in value)
