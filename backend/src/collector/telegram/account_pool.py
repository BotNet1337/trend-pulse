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
    POOL_FAILING_NO_READ_WINDOW_SECONDS,
    POOL_FAILING_THRESHOLD,
    POOL_MAX,
    POOL_MIN,
    POOL_SOURCE_MANUAL,
    QUARANTINE_PERSIST_TTL_SECONDS,
    QUARANTINE_REDIS_KEY,
    SESSION_FINGERPRINT_LEN,
)
from collector.errors import (
    AllAccountsFloodWaitError,
    InvalidProxyError,
    PoolConfigError,
    PoolExhaustedError,
)
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
    # Read-outcome bookkeeping (TASK-118), set by the reader's success / transient-error
    # catch sites. Annotation-only — they NEVER change rotation/cooldown/quarantine.
    #   * `last_read_ok_at` — monotonic stamp of the last CLEAN read (None until first OK).
    #   * `consecutive_read_failures` — count of read failures since the last clean read
    #     (reset to 0 on success). Drives the `failing` classification.
    #   * `first_read_failure_at` — monotonic stamp of the FIRST read failure since the
    #     last clean read; the no-read-window timer starts here so a never-read-but-erroring
    #     account is eventually surfaced as failing without alarming a freshly booted pool.
    last_read_ok_at: float | None = None
    consecutive_read_failures: int = 0
    first_read_failure_at: float | None = None
    # CUMULATIVE read-failure tally for this account (pool-admin UI): unlike
    # `consecutive_read_failures` (reset on every clean read to drive the `failing`
    # classification), this counter is NEVER reset by an intermittent success, so the UI
    # can show how OFTEN a session has failed even when it occasionally succeeds (the
    # "wrong session ID"/SecurityError case). Reset to 0 only on a slot revive. Non-secret.
    read_failure_count: int = 0
    # The dynamic-store account identity (TASK-119): the `tg_user_id` from `get_me()`
    # for a slot loaded from the DB store, so a revive-signal can target THIS slot by
    # identity (None for an env-only bootstrap slot). NEVER a secret.
    tg_user_id: int | None = None
    # The NON-SECRET display label (TASK-120): a masked id / `@username` from the store,
    # surfaced in the health snapshot so the UI labels each row by account (None for an
    # env-only bootstrap slot with no store identity). NEVER a secret (not the session).
    display_label: str | None = None
    # FIX 2 (TASK-129): the per-session SOCKS5 proxy URI this slot was built with.
    # This is a SECRET (carries user:pass credentials) and must NEVER appear in logs,
    # AccountStatus, health snapshots, or Redis. Held here so revive_slot can rebuild
    # the new client with the SAME egress IP — the account keeps its proxy affinity
    # across a session re-mint.
    proxy: str | None = None
    # Non-secret provenance (TASK-130): `manual` (owner via QR) vs `auto` (account-factory,
    # TASK-134). Carried from the DB row through the health snapshot to the pool-admin UI
    # badge. Env bootstrap slots default to `manual` (owner-provisioned). NEVER a secret.
    source: str = POOL_SOURCE_MANUAL


# Account lifecycle state exposed in the health snapshot (TASK-115; `failing` TASK-118).
AccountState = Literal["healthy", "cooling", "quarantined", "failing"]


@dataclass(frozen=True)
class AccountStatus:
    """Read-only, immutable per-account health view for the snapshot (TASK-115).

    Carries NO secrets: `index` is the stable pool position (the only per-account
    identifier), never the session string or fingerprint. `cooldown_remaining_seconds`
    is populated only for a cooling account (None otherwise). `last_error_reason` is the
    last-known reason (may persist after recovery — acceptable, last-known).

    `display_label`/`tg_user_id` (TASK-120) are the NON-SECRET store identity for a
    DB-loaded slot (masked id / `@username` / numeric id), None for an env-only slot —
    so the UI labels rows by account, never by session string.
    """

    index: int
    state: AccountState
    cooldown_remaining_seconds: float | None
    last_error_reason: str
    display_label: str | None = None
    tg_user_id: int | None = None
    # CUMULATIVE read-failure count (pool-admin UI): how often this account's reads have
    # failed (e.g. the "wrong session ID"/SecurityError loop), so the owner sees error
    # FREQUENCY, not just the last reason. Never reset by an intermittent success. Non-secret.
    read_failure_count: int = 0
    # Non-secret provenance (TASK-130): `manual` (owner via QR) vs `auto` (account-factory).
    # This is what `asdict()` serialises into the snapshot, so the pool-admin UI can badge
    # each row. Default `manual`. NEVER a secret.
    source: str = POOL_SOURCE_MANUAL


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
    # The client factory the pool was built from (TASK-119): retained so a single-slot
    # revive can build a fresh client over a NEW session string. None only for legacy
    # constructions that never revive (the dataclass default keeps back-compat).
    _factory: TelegramClientFactory | None = None

    @classmethod
    def from_sessions(
        cls,
        *,
        sessions: list[str],
        factory: TelegramClientFactory,
        redis: "Redis | None" = None,
        tg_user_ids: list[int | None] | None = None,
        display_labels: list[str | None] | None = None,
        proxies: list[str | None] | None = None,
        sources: list[str | None] | None = None,
    ) -> "AccountPool":
        """Build a pool from pool session strings; validates size POOL_MIN..POOL_MAX.

        When `redis` is given, the persisted quarantine set (TASK-102) is loaded and any
        account whose fingerprint is present is marked quarantined at construction — so a
        dead session stays quarantined across worker restarts/recycling (not re-tried, and
        the boot-time `healthy` count is accurate). Fail-open: a Redis error logs a warning
        and builds the pool in-memory-only (construction must never crash on a Redis blip).

        `tg_user_ids` (TASK-119, optional) is the per-session Telegram account identity
        (positional with `sessions`); a DB-store slot carries its `tg_user_id` so a
        revive-signal can target it by identity. Env bootstrap slots pass None. The
        `factory` is retained so a revive can build a fresh client for the swapped slot.

        `display_labels` (TASK-120, optional) is the per-session NON-SECRET display label
        (positional with `sessions`); a DB-store slot carries its masked id / `@username`
        so the health snapshot can label the row by account. Env slots pass None.

        `proxies` (TASK-129, optional) is the per-session SOCKS5 proxy URI (positional
        with `sessions`). When an entry is a non-None string, `factory(session, proxy)` is
        called with that URI; when None, `factory(session, None)` preserves today's
        byte-identical no-proxy path. A `InvalidProxyError` raised by the factory for a
        single slot is caught here: the slot is SKIPPED with a WARNING (no secret — only
        the slot index is logged), and the remaining slots build normally. This gives
        per-slot fail-closed isolation: one bad proxy degrades exactly one slot.

        `sources` (TASK-130, optional) is the per-session NON-SECRET provenance (positional
        with `sessions`): `manual` (owner via QR) or `auto` (account-factory). A None list
        or a None entry defaults to `manual`. Carried into each slot's `AccountStatus` so the
        pool-admin UI can badge each row by provenance. Validated like the other lists.
        """
        size = len(sessions)
        if size < POOL_MIN or size > POOL_MAX:
            raise PoolConfigError(
                f"telegram pool must have between {POOL_MIN} and {POOL_MAX} "
                f"technical accounts, got {size}"
            )
        ids: list[int | None] = tg_user_ids if tg_user_ids is not None else [None] * size
        if len(ids) != size:
            raise PoolConfigError(f"tg_user_ids length ({len(ids)}) must match sessions ({size})")
        labels: list[str | None] = display_labels if display_labels is not None else [None] * size
        if len(labels) != size:
            raise PoolConfigError(
                f"display_labels length ({len(labels)}) must match sessions ({size})"
            )
        proxy_list: list[str | None] = proxies if proxies is not None else [None] * size
        if len(proxy_list) != size:
            raise PoolConfigError(
                f"proxies length ({len(proxy_list)}) must match sessions ({size})"
            )
        source_list: list[str | None] = sources if sources is not None else [None] * size
        if len(source_list) != size:
            raise PoolConfigError(
                f"sources length ({len(source_list)}) must match sessions ({size})"
            )
        accounts: list[_Account] = []
        # FIX 4: use enumerate to get the true INPUT position for the skip warning —
        # len(accounts) shifts after an earlier skip, making the log message misleading.
        for input_index, (session, tg_user_id, display_label, proxy, source) in enumerate(
            zip(sessions, ids, labels, proxy_list, source_list, strict=True)
        ):
            try:
                client = factory(session, proxy)
            except InvalidProxyError:
                # Per-slot fail-closed (AC3): log the INPUT slot index only — NEVER the
                # proxy URI (it carries user:pass credentials). Skip this slot; others
                # build normally.
                logger.warning(
                    "invalid proxy for pool slot %d — skipping this slot (proxy not logged)",
                    input_index,
                )
                continue
            accounts.append(
                _Account(
                    client=client,
                    fingerprint=session_fingerprint(session),
                    tg_user_id=tg_user_id,
                    display_label=display_label,
                    # FIX 2: store the per-slot proxy URI so revive_slot can thread it
                    # to the factory when rebuilding this slot's client after a re-mint.
                    # SECRET — never logged, never in AccountStatus/snapshots/Redis.
                    proxy=proxy,
                    # TASK-130: non-secret provenance; default `manual` when None.
                    source=source if source is not None else POOL_SOURCE_MANUAL,
                )
            )
        # After per-slot skip: the built pool may be smaller than `size`. Validate
        # POOL_MIN..POOL_MAX on the ACTUAL number of successfully-built accounts.
        actual = len(accounts)
        if actual < POOL_MIN or actual > POOL_MAX:
            raise PoolConfigError(
                f"telegram pool must have between {POOL_MIN} and {POOL_MAX} "
                f"technical accounts after proxy filtering, got {actual}"
            )
        persisted = cls._load_quarantined_fingerprints(redis)
        for account in accounts:
            if account.fingerprint in persisted:
                account.quarantined = True
        return cls(_accounts=accounts, _redis=redis, _factory=factory)

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
            elif self._is_failing(account, now):
                # Live (not quarantined/cooling) but its reads persistently fail —
                # observational only (TASK-118); `acquire()` is UNAFFECTED.
                state = "failing"
                cooldown_remaining = None
            else:
                state = "healthy"
                cooldown_remaining = None
            statuses.append(
                AccountStatus(
                    index=index,
                    state=state,
                    cooldown_remaining_seconds=cooldown_remaining,
                    last_error_reason=account.last_error_reason,
                    display_label=account.display_label,
                    tg_user_id=account.tg_user_id,
                    read_failure_count=account.read_failure_count,
                    source=account.source,
                )
            )
        return statuses

    @staticmethod
    def _is_failing(account: _Account, now: float) -> bool:
        """Classify a LIVE account (not quarantined/cooling) as `failing` (TASK-118).

        Failing iff its reads persistently fail: either `POOL_FAILING_THRESHOLD`
        consecutive read failures, OR it has errored at least once, never once read OK,
        and the no-read window has elapsed since its FIRST failure. Pure + side-effect
        free; FLOOD_WAIT cooling is handled by the caller (precedence) and never reaches
        here as a read failure (it does not increment the counter).
        """
        if account.consecutive_read_failures >= POOL_FAILING_THRESHOLD:
            return True
        return (
            account.last_read_ok_at is None
            and account.first_read_failure_at is not None
            and now - account.first_read_failure_at >= POOL_FAILING_NO_READ_WINDOW_SECONDS
        )

    def note_read_success(self) -> None:
        """Record a CLEAN read on the CURRENT account (TASK-118).

        Stamps `last_read_ok_at` (monotonic) and resets the consecutive-failure counter
        and the no-read window, so a recovered account leaves `failing`. DELIBERATELY KEEPS
        `last_error_reason` AND the cumulative `read_failure_count` (last-known, consistent
        with TASK-115) — so a session that mostly fails but occasionally succeeds (the
        "wrong session ID"/SecurityError case) still shows its error + failure frequency in
        the pool-admin UI. Annotation only — does NOT change rotation/cooldown/quarantine.
        Called by the reader alongside `report_success()` after a clean iteration.
        """
        if self._accounts:
            account = self._accounts[self._index]
            account.last_read_ok_at = self._clock()
            account.consecutive_read_failures = 0
            account.first_read_failure_at = None

    def note_read_failure(self, reason: str) -> None:
        """Record a READ FAILURE on the CURRENT account (TASK-118).

        Increments the consecutive-failure counter, stamps the no-read window start on
        the FIRST failure since the last clean read, and records the non-fatal `reason`
        (an error CLASS NAME, e.g. the "wrong session ID" Telethon error — NEVER a
        session string). Called by the reader at the currently-silent transient catch
        site. Annotation only — does NOT change rotation/cooldown/quarantine, and is
        DISTINCT from FLOOD_WAIT (which is cooling, not a read failure).
        """
        if self._accounts:
            account = self._accounts[self._index]
            account.consecutive_read_failures += 1
            # Cumulative tally for the UI — never reset by an intermittent success (only on
            # revive), so the owner sees how OFTEN a session has failed (TASK-118 follow-up).
            account.read_failure_count += 1
            if account.first_read_failure_at is None:
                account.first_read_failure_at = self._clock()
            account.last_error_reason = reason

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

    def find_slot_index(self, *, tg_user_id: int | None, fingerprint: str) -> int | None:
        """Locate the slot for a revive by identity (TASK-119); None if not present.

        Prefers the `tg_user_id` match (the stable account identity); falls back to the
        OLD `fingerprint` (the dead session's sha256[:16]) so a slot loaded before it had
        an identity, or matched only by its prior session, is still found. Pure lookup —
        no mutation. Returns the first matching slot index, or None when no slot matches
        (a brand-new account that will appear on the next full pool build instead).
        """
        if tg_user_id is not None:
            for idx, account in enumerate(self._accounts):
                if account.tg_user_id == tg_user_id:
                    return idx
        if fingerprint:
            for idx, account in enumerate(self._accounts):
                if account.fingerprint == fingerprint:
                    return idx
        return None

    async def revive_slot(
        self,
        *,
        slot_index: int,
        tg_user_id: int,
        session_string: str,
        display_label: str | None = None,
    ) -> None:
        """SAFELY swap ONE slot's client to a NEW session (disconnect-then-connect).

        The crux of the ADR's safety case (TASK-119). For the SINGLE slot `slot_index`:
          1. `await old_client.disconnect()` FIRST — the dead/old session's client is
             fully torn down before anything new connects (best-effort: a disconnect
             failure on a dead socket is logged, not raised — the point is to never
             DOUBLE-connect, which a failed disconnect on a dead socket does not).
          2. build a fresh client over the NEW `session_string` via the retained factory
             and `connect()` it.
          3. swap `account.client` in place and reset THIS slot's transient state
             (`quarantined`/cooldown/strikes/read-outcome/`last_error_reason`) and update
             its `fingerprint`/`tg_user_id` to the new session — so the revived slot
             leaves `failing`/`quarantined` and starts clean.

        INVARIANT: a session is never connected by two clients at once — the old client
        is disconnected before the new client connects, and ONLY this slot is touched
        (no other `_Account.client` is reconnected). The session string is a secret and
        is NEVER logged. Raises `PoolConfigError` if the slot index is out of range or
        no factory is available (a misconstructed pool that cannot revive).

        Belt-and-suspenders (TASK-119 fix): the swapped-out OLD fingerprint is SREM'd from
        the persisted quarantine set so a worker recycle after this revive does not reload
        the slot as dead — even if the producer's `clear_quarantine_for` was skipped/failed.
        Fail-open: a Redis error is logged, never raised (mirrors `_persist_quarantine`).
        """
        if self._factory is None:
            raise PoolConfigError("pool has no client factory; cannot revive a slot")
        if slot_index < 0 or slot_index >= len(self._accounts):
            raise PoolConfigError(f"revive slot index {slot_index} out of range")

        account = self._accounts[slot_index]
        old_client = account.client
        old_fingerprint = account.fingerprint
        # 1. Disconnect the OLD client FIRST — best-effort (the old socket is dead).
        try:
            await old_client.disconnect()
        except Exception:
            # Log, never raise: a failed disconnect on a dead socket does NOT leave the
            # session double-connected, and must not block the revive (Invariant).
            logger.warning("old client disconnect failed during revive (proceeding)")

        # 2. Build + connect the NEW client (only after the old one is down).
        # FIX 2 (TASK-129): thread the slot's existing proxy to the factory — the proxy
        # assignment is per-account/IP affinity (the account keeps its dedicated egress
        # IP across a re-mint). account.proxy is a SECRET and is never logged here.
        new_client = self._factory(session_string, account.proxy)
        await new_client.connect()

        # 3. Swap in place + reset THIS slot's state (single-slot only).
        account.client = new_client
        account.tg_user_id = tg_user_id
        # Refresh the non-secret display label for the revived slot (TASK-120); keep the
        # prior label when the caller does not supply one (env-only revive path).
        if display_label is not None:
            account.display_label = display_label
        account.fingerprint = session_fingerprint(session_string)
        account.quarantined = False
        account.cooldown_until = 0.0
        account.flood_strikes = 0
        account.consecutive_read_failures = 0
        account.read_failure_count = 0
        account.first_read_failure_at = None
        account.last_read_ok_at = None
        account.last_error_reason = ""

        # 4. Belt-and-suspenders: drop the OLD fingerprint from the persisted quarantine
        # set so a worker recycle after this revive does not reload the slot as dead.
        self._clear_persisted_quarantine(old_fingerprint)

    def _clear_persisted_quarantine(self, fingerprint: str) -> None:
        """SREM a revived slot's OLD fingerprint from the persisted quarantine set.

        Best-effort, fail-open (TASK-119): `redis=None`, an empty/malformed fingerprint,
        or a Redis error is a no-op/logged-and-swallowed — never raised (mirrors
        `_persist_quarantine` + `pool_session_store.clear_quarantine_for`). NEVER a secret.
        """
        if self._redis is None or not _is_valid_fingerprint(fingerprint):
            return
        try:
            self._redis.srem(QUARANTINE_REDIS_KEY, fingerprint)
        except RedisError:
            logger.warning("could not clear quarantine on revive (Redis); ignoring")

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
