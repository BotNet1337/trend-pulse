"""Pool of technical Telegram accounts with FLOOD_WAIT rotation (AC4, AC8).

Each account is one pool StringSession (env: TELEGRAM_POOL_SESSIONS) sharing the
api_id/api_hash. The pool picks an active (not cooling-down) account; on a
FLOOD_WAIT it marks that account cooling-down with exponential backoff and rotates
to the next. When every account is cooling down it raises
`AllAccountsFloodWaitError` so the caller backs off (never crashes the collector).

Secrets (session strings, api_hash) are stored but NEVER logged. There is no user
`session_string` concept — only pool technical accounts (overview §2/§7).
"""

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, cast

from redis.exceptions import RedisError

from collector.constants import (
    BACKOFF_BASE_SECONDS,
    BACKOFF_CAP_SECONDS,
    POOL_MAX,
    POOL_MIN,
    QUARANTINE_PERSIST_TTL_SECONDS,
    QUARANTINE_REDIS_KEY,
    SESSION_FINGERPRINT_LEN,
)
from collector.errors import AllAccountsFloodWaitError, PoolConfigError, PoolExhaustedError
from collector.telegram.client import TelegramClientFactory, TelegramClientProtocol

if TYPE_CHECKING:
    from redis import Redis

logger = logging.getLogger(__name__)


def session_fingerprint(session: str) -> str:
    """Non-secret, stable fingerprint of a pool session string (TASK-102).

    `sha256(session)[:16]` — one-way (cannot recover the session), so it is safe to
    store/log, yet stable per session and DIFFERENT for a re-minted session (so a
    re-minted session is never wrongly loaded as quarantined). Used as the persistent
    quarantine key; the session string itself is never stored or logged (overview §7).
    """
    return hashlib.sha256(session.encode("utf-8")).hexdigest()[:SESSION_FINGERPRINT_LEN]


def _is_valid_fingerprint(value: str) -> bool:
    """A well-formed fingerprint is exactly SESSION_FINGERPRINT_LEN lowercase hex chars.

    Defense-in-depth on the Redis read (TASK-102 security review): a corrupted/poisoned
    set member that isn't a real fingerprint can never match a live account anyway (strict
    equality), but filtering keeps the trust boundary explicit.
    """
    return len(value) == SESSION_FINGERPRINT_LEN and all(c in "0123456789abcdef" for c in value)


@dataclass
class _Account:
    """One pool account: its client plus FLOOD_WAIT cooldown state.

    `cooldown_until` is a monotonic deadline (seconds); `flood_strikes` drives the
    exponential backoff growth. The session string itself is held by the factory
    closure, not stored here, so it never leaks into logs/reprs.
    """

    client: TelegramClientProtocol
    cooldown_until: float = 0.0
    flood_strikes: int = 0
    # PERMANENT eviction (TASK-087): a dead session (AuthKeyDuplicated/UserDeactivated/
    # SessionRevoked) is quarantined for the life of the pool — `acquire()` never hands
    # it out again. This is the Redis-independent dedup that stops the alert-spam loop.
    quarantined: bool = False
    # Non-secret sha256[:16] of this account's session string (TASK-102): the key under
    # which a quarantine is persisted in Redis so it survives a worker restart/recycle.
    fingerprint: str = ""
    # Most-recent error reason for this account (TASK-115): the permanent-auth error
    # CLASS NAME (e.g. "AuthKeyDuplicatedError") or "FLOOD_WAIT", set by the reader at
    # the existing catch sites. Last-known only (not history); NEVER a session string.
    last_error_reason: str = ""


# Account lifecycle state exposed in the health snapshot (TASK-115).
AccountState = Literal["healthy", "cooling", "quarantined"]


@dataclass(frozen=True)
class AccountStatus:
    """Read-only, immutable per-account health view for the snapshot (TASK-115).

    Carries NO secrets: `index` is the stable pool position (the only per-account
    identifier), never the session string or fingerprint. `cooldown_remaining_seconds`
    is populated only for a cooling account (None otherwise). `last_error_reason` is the
    last-known reason (may persist after recovery — acceptable, last-known).
    """

    index: int
    state: AccountState
    cooldown_remaining_seconds: float | None
    last_error_reason: str


def _backoff_seconds(strikes: int) -> float:
    """Exponential backoff: base * 2**(strikes-1), capped (seconds)."""
    if strikes <= 0:
        return 0.0
    raw = BACKOFF_BASE_SECONDS * (2 ** (strikes - 1))
    return float(min(raw, BACKOFF_CAP_SECONDS))


@dataclass
class AccountPool:
    """Rotating pool of technical accounts (3..10), fail-fast on misconfig."""

    _accounts: list[_Account] = field(default_factory=list)
    _index: int = 0
    # Injectable monotonic clock (seconds) so tests can advance time deterministically.
    _now: Callable[[], float] = time.monotonic
    # Optional Redis for PERSISTENT quarantine (TASK-102); None = in-memory only.
    _redis: "Redis | None" = None

    @classmethod
    def from_sessions(
        cls,
        *,
        sessions: list[str],
        factory: TelegramClientFactory,
        redis: "Redis | None" = None,
    ) -> "AccountPool":
        """Build a pool from pool session strings; validates size POOL_MIN..POOL_MAX.

        When `redis` is given, the persisted quarantine set (TASK-102) is loaded and any
        account whose fingerprint is present is marked quarantined at construction — so a
        dead session stays quarantined across worker restarts/recycling (not re-tried, and
        the boot-time `healthy` count is accurate). Fail-open: a Redis error logs a warning
        and builds the pool in-memory-only (construction must never crash on a Redis blip).
        """
        size = len(sessions)
        if size < POOL_MIN or size > POOL_MAX:
            raise PoolConfigError(
                f"telegram pool must have between {POOL_MIN} and {POOL_MAX} "
                f"technical accounts, got {size}"
            )
        accounts = [
            _Account(client=factory(session), fingerprint=session_fingerprint(session))
            for session in sessions
        ]
        persisted = cls._load_quarantined_fingerprints(redis)
        for account in accounts:
            if account.fingerprint in persisted:
                account.quarantined = True
        return cls(_accounts=accounts, _redis=redis)

    @staticmethod
    def _load_quarantined_fingerprints(redis: "Redis | None") -> frozenset[str]:
        """Read the persisted quarantine fingerprint set (TASK-102); fail-open to empty."""
        if redis is None:
            return frozenset()
        try:
            # smembers is bytes with decode_responses=False (get_redis_client default),
            # str if True — handle both so a config change can't crash pool boot. Cast to
            # a concrete union (not Any) so mypy reasons about the members.
            members = cast("set[bytes | str]", redis.smembers(QUARANTINE_REDIS_KEY))
        except RedisError:
            logger.warning("could not load persisted quarantine (Redis); in-memory only")
            return frozenset()
        decoded = (m if isinstance(m, str) else m.decode("utf-8") for m in members)
        return frozenset(fp for fp in decoded if _is_valid_fingerprint(fp))

    def _clock(self) -> float:
        return float(self._now())

    def __len__(self) -> int:
        return len(self._accounts)

    @property
    def size(self) -> int:
        """Total number of accounts in the pool (read-only, no behaviour change)."""
        return len(self._accounts)

    @property
    def cooling_count(self) -> int:
        """Number of LIVE accounts currently in FLOOD_WAIT cooldown (read-only).

        Quarantined (dead) accounts are excluded — they are counted by
        `quarantined_count`, not double-counted here (TASK-087).
        """
        now = self._clock()
        return sum(1 for a in self._accounts if not a.quarantined and a.cooldown_until > now)

    @property
    def quarantined_count(self) -> int:
        """Number of permanently quarantined (dead-session) accounts (TASK-087)."""
        return sum(1 for a in self._accounts if a.quarantined)

    def account_statuses(self) -> list[AccountStatus]:
        """Read-only per-account health view for the cross-process snapshot (TASK-115).

        Mirrors the `cooling_count` clock logic (a LIVE account whose
        `cooldown_until > now` is cooling); quarantine takes precedence over cooling.
        Returns one `AccountStatus` per pool account in index order. NO mutation, NO
        secrets — `index` is the only per-account identifier. An empty pool returns `[]`.
        """
        now = self._clock()
        statuses: list[AccountStatus] = []
        for index, account in enumerate(self._accounts):
            if account.quarantined:
                state: AccountState = "quarantined"
                cooldown_remaining: float | None = None
            elif account.cooldown_until > now:
                state = "cooling"
                cooldown_remaining = account.cooldown_until - now
            else:
                state = "healthy"
                cooldown_remaining = None
            statuses.append(
                AccountStatus(
                    index=index,
                    state=state,
                    cooldown_remaining_seconds=cooldown_remaining,
                    last_error_reason=account.last_error_reason,
                )
            )
        return statuses

    def note_current_error(self, reason: str) -> None:
        """Record the last-known error `reason` on the CURRENT account (TASK-115).

        Called by the reader at the existing catch sites BEFORE rotation/quarantine, so
        the reason lands on the account that actually failed. Does NOT change rotation,
        cooldown, or quarantine semantics — it only annotates for the health snapshot.
        `reason` is a class name or "FLOOD_WAIT", NEVER a session string.
        """
        if self._accounts:
            self._accounts[self._index].last_error_reason = reason

    def acquire(self) -> TelegramClientProtocol:
        """Return the client of the next account that is live and not cooling down.

        Raises `AllAccountsFloodWaitError` when every LIVE account is cooling down
        (they recover after cooldown), and `PoolExhaustedError` when EVERY account
        is quarantined (dead sessions — only re-minting recovers; never retry/sleep
        on this — TASK-087).
        """
        if not self._accounts:
            raise PoolConfigError("account pool is empty")
        now = self._clock()
        count = len(self._accounts)
        has_live = False  # at least one non-quarantined account exists
        for offset in range(count):
            idx = (self._index + offset) % count
            account = self._accounts[idx]
            if account.quarantined:
                continue
            has_live = True
            if account.cooldown_until <= now:
                self._index = idx
                return account.client
        if not has_live:
            raise PoolExhaustedError(
                "every pool account is quarantined (dead sessions) — re-mint sessions"
            )
        raise AllAccountsFloodWaitError("all pool accounts are cooling down under FLOOD_WAIT")

    def quarantine_current(self) -> int:
        """Permanently evict the current account (dead session) and rotate.

        Returns the account's stable pool index as a NON-SECRET fingerprint for the
        ops alert (never the session string). A quarantined account is never handed
        out by `acquire()` again for the life of this pool/process — the durable,
        Redis-independent dedup that stops the AuthKeyDuplicated alert-spam loop.
        """
        if not self._accounts:
            raise PoolConfigError("account pool is empty")
        idx = self._index
        account = self._accounts[idx]
        account.quarantined = True
        self._persist_quarantine(account.fingerprint)
        self._index = (self._index + 1) % len(self._accounts)
        return idx

    def _persist_quarantine(self, fingerprint: str) -> None:
        """Persist a dead-session fingerprint so the quarantine survives restarts
        (TASK-102). Best-effort: a Redis failure logs and is swallowed — the in-memory
        quarantine still holds for this process, so a persistence blip never re-enables
        a dead session within the running pool."""
        if self._redis is None or not fingerprint:
            return
        try:
            # SADD + EXPIRE atomically in one pipeline so the key can never be left
            # without a TTL on a partial failure (review MEDIUM) — mirrors buffer.write_post.
            pipe = self._redis.pipeline()
            pipe.sadd(QUARANTINE_REDIS_KEY, fingerprint)
            pipe.expire(QUARANTINE_REDIS_KEY, QUARANTINE_PERSIST_TTL_SECONDS)
            pipe.execute()
        except RedisError:
            logger.warning("could not persist session quarantine (Redis); in-memory only")

    def report_flood_wait(self, *, retry_after_seconds: float | None = None) -> None:
        """Mark the current account cooling down and rotate to the next.

        Uses Telegram's `retry_after` hint when given, else exponential backoff
        derived from the account's accumulated strike count.
        """
        if not self._accounts:
            raise PoolConfigError("account pool is empty")
        account = self._accounts[self._index]
        account.flood_strikes += 1
        wait = (
            float(retry_after_seconds)
            if retry_after_seconds is not None
            else _backoff_seconds(account.flood_strikes)
        )
        account.cooldown_until = self._clock() + wait
        self._index = (self._index + 1) % len(self._accounts)

    def report_success(self) -> None:
        """Reset the current account's backoff growth after a clean request."""
        if self._accounts:
            self._accounts[self._index].flood_strikes = 0

    def cooldown_remaining(self) -> float:
        """Smallest remaining cooldown across LIVE accounts (seconds); 0 if any ready.

        Quarantined accounts are excluded: a dead session has no meaningful cooldown
        and must not make the caller believe an account is "about to be ready"
        (TASK-087 — that would loop `_acquire_ready_client` on a sleep(0)).
        """
        now = self._clock()
        remaining = [max(0.0, a.cooldown_until - now) for a in self._accounts if not a.quarantined]
        if not remaining:
            return 0.0
        ready = [r for r in remaining if r <= 0.0]
        if ready:
            return 0.0
        return min(remaining)

    async def aclose(self) -> None:
        """Disconnect every pool client (worker shutdown / collector teardown).

        Without this, clients connected on acquire stay open for the life of the
        worker — a socket/session leak. Disconnect failures are logged, not raised,
        so one bad client can't block closing the rest.
        """
        for account in self._accounts:
            try:
                await account.client.disconnect()
            except Exception:
                # Best-effort teardown — log (not swallow) so one bad client can't
                # block closing the rest; never re-raise during shutdown.
                logger.warning("pool client disconnect failed during aclose")
