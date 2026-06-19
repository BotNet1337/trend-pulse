"""`TelegramCollector` — the Telegram `SourceCollector` (AC2/AC3/AC4/AC5).

Telegram specifics (Telethon errors, entity resolution, iteration) are confined to
this module plus `account_pool`/`mapper`/`dedup`. `read` builds the UNION of unique
refs (cross-tenant dedup), reads each channel once, maps each message via the pure
mapper, and on FLOOD_WAIT applies backoff + account rotation without crashing.

Pool health (TASK-035): `emit_pool_health` + `notify_ops` are called best-effort at
key degradation points — they never propagate exceptions (Invariant: self-observation
must not crash collection).
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING, cast

from redis.exceptions import RedisError

from collector.base import RawPost, SourceKind, SourceRef
from collector.constants import (
    FLOOD_WAIT_INLINE_CAP_SECONDS,
    INTER_REQUEST_SLEEP_SECONDS,
    MAX_MESSAGES_PER_TICK,
    POOL_REVIVE_SIGNAL_REDIS_KEY,
    SESSION_FINGERPRINT_LEN,
)
from collector.errors import (
    AllAccountsFloodWaitError,
    PoolExhaustedError,
    SourceUnavailableError,
)
from collector.telegram.account_pool import AccountPool
from collector.telegram.auth_errors import is_permanent_auth_error
from collector.telegram.client import TelegramClientProtocol
from collector.telegram.dedup import normalize_handle, unique_refs
from collector.telegram.mapper import map_entity

if TYPE_CHECKING:
    from redis import Redis

    from config import Settings
    from storage.pool_session_store import StoredSession

logger = logging.getLogger(__name__)


def _is_valid_fingerprint(value: str) -> bool:
    """A well-formed fingerprint: exactly SESSION_FINGERPRINT_LEN lowercase hex chars.

    Mirrors `account_pool._is_valid_fingerprint` — a poisoned revive-signal member
    that isn't a real fingerprint is rejected before it can reach `revive_slot`.
    """
    return len(value) == SESSION_FINGERPRINT_LEN and all(c in "0123456789abcdef" for c in value)


# Telethon error types are resolved lazily (the SDK is imported only when present)
# so this module imports cleanly in pure-unit contexts. We match on a `seconds`
# attribute structurally rather than importing FloodWaitError at module load.
_AsyncSleep = Callable[[float], Awaitable[None]]


def _flood_wait_seconds(error: BaseException) -> float | None:
    """Return the FLOOD_WAIT retry hint if `error` looks like a FloodWaitError."""
    seconds = getattr(error, "seconds", None)
    if isinstance(seconds, int | float):
        return float(seconds)
    return None


async def _ensure_connected(client: TelegramClientProtocol) -> None:
    """Connect `client` only if it is not connected yet.

    Re-calling `connect()` on a live Telethon client logs "User is already
    connected!" and was part of the prod hang signature (pool=1 "rotation"
    re-acquired the same connected account every retry).
    """
    if not client.is_connected():
        await client.connect()


class TelegramCollector:
    """Telegram implementation of the `SourceCollector` port."""

    kind: SourceKind = SourceKind.TELEGRAM

    def __init__(
        self,
        pool: AccountPool,
        *,
        sleep: _AsyncSleep | None = None,
        settings: "Settings | None" = None,
        redis: "Redis | None" = None,
    ) -> None:
        self._pool = pool
        # Injectable async sleep keeps unit tests instant (no real backoff waits).
        self._sleep: _AsyncSleep = sleep if sleep is not None else asyncio.sleep
        # Optional: settings + redis for pool health self-observation (TASK-035).
        # When None, health calls are skipped — unit tests and backwards-compat.
        self._settings = settings
        self._redis = redis

    def _emit_health_best_effort(
        self,
        *,
        notify_reason: str | None = None,
        notify_text: str | None = None,
        emit_metric: bool = True,
    ) -> None:
        """Emit pool health metric + optionally send an ops self-alert (best-effort).

        `emit_metric` (TASK-118) controls the once-per-tick semantics of the
        `pool_health` METRIC + Redis snapshot write: the periodic summary at the end of
        `read()` keeps `emit_metric=True` (the single emit per collect cycle), while the
        notify-only degradation sites (auth_error / all_flood / pool_exhausted /
        auth_dead) call with `emit_metric=False` so they ONLY throttle-notify and do NOT
        re-emit the metric per-channel/per-acquire (prod was seeing ~1 emit/sec). The
        ops self-alert keeps its own Redis throttle in all cases.

        NEVER raises — swallows all exceptions with a warn log so self-observation
        cannot crash the collector (Invariant).  When settings/redis are None (unit
        tests, backwards-compat callers) the call is a silent no-op.
        """
        if self._settings is None or self._redis is None:
            return
        try:
            from observability.pool_health import emit_pool_health, notify_ops

            # Pass redis so the full snapshot is bridged to `pool:health:latest`
            # for the API to read cross-process (TASK-115); best-effort write. Only the
            # once-per-tick caller emits the metric/snapshot (TASK-118 cadence fix).
            result = (
                emit_pool_health(self._pool, self._settings, self._redis) if emit_metric else None
            )
            if notify_reason is not None and notify_text is not None:
                notify_ops(
                    reason=notify_reason,
                    text=notify_text,
                    settings=self._settings,
                    redis=self._redis,
                )
            elif result is not None and result["degraded"] and notify_reason is None:
                # Periodic tick: degraded → self-alert without an explicit reason.
                notify_ops(
                    reason="pool_below_target",
                    text=(
                        f"TG pool degraded: {result['healthy']} healthy, "
                        f"target {result['target']}, cooling {result['cooling']}"
                    ),
                    settings=self._settings,
                    redis=self._redis,
                )
        except Exception as exc:
            logger.warning(
                "pool health observation failed",
                extra={"exc_type": type(exc).__name__},
            )

    async def apply_pending_revive(self) -> None:
        """Apply a pending single-slot revive-signal ONCE per collect cycle (TASK-119).

        The collect tick (`collector.tasks`) calls this exactly ONCE at the start of a
        cycle, before its per-ref `read()` loop, so the revive-signal Redis GET fires a
        SINGLE time per tick (not once per ref — there are ~108 refs/tick). Public so the
        tick wrapper can drive it; the disconnect-before-connect single-slot revive
        invariant is unchanged (it still applies at a tick boundary, never mid-read).
        NEVER raises (best-effort — mirrors `_emit_health_best_effort`).
        """
        await self._apply_revive_best_effort()

    async def _apply_revive_best_effort(self) -> None:
        """Apply a pending single-slot revive-signal at a tick boundary (TASK-119).

        Reads the NON-SECRET revive-signal from Redis (`pool:revive:signal` — only the
        affected slot's `tg_user_id`/`fingerprint`, NEVER the session string). If it
        targets a live slot, loads the NEW session for that account from the encrypted
        DB store (the secret comes from the DB, never from Redis), and calls
        `pool.revive_slot(...)` which disconnects the old client before connecting the
        new one — touching ONLY that slot. Clears the signal afterward so it applies
        once. NEVER raises: a missing signal, a malformed payload, a Redis/DB error, or
        a slot-not-found self-heals (the next full pool build unions the DB store), and
        must not crash the collect tick (Invariant — mirrors `_emit_health_best_effort`).
        """
        if self._redis is None:
            return
        try:
            signal = self._read_revive_signal()
            if signal is None:
                return
            tg_user_id, fingerprint = signal
            slot_index = self._pool.find_slot_index(tg_user_id=tg_user_id, fingerprint=fingerprint)
            if slot_index is None:
                # Brand-new account (not in the live pool) — appears on the next full
                # pool build; clear the signal so we don't re-check it every tick.
                self._clear_revive_signal()
                return
            stored = self._load_stored_session(tg_user_id)
            if stored is None:
                self._clear_revive_signal()
                return
            await self._pool.revive_slot(
                slot_index=slot_index,
                tg_user_id=tg_user_id,
                session_string=stored.session_string,
                display_label=stored.display_label or None,
            )
            self._clear_revive_signal()
            logger.info("applied pool revive for slot", extra={"slot_index": slot_index})
        except Exception as exc:
            # Self-observation/remediation must NEVER crash the tick (Invariant). Log the
            # class name only (never a secret) and move on; the next build self-heals.
            logger.warning(
                "pool revive application failed (ignored)",
                extra={"exc_type": type(exc).__name__},
            )

    def _read_revive_signal(self) -> tuple[int, str] | None:
        """Parse the NON-SECRET revive-signal JSON; None if absent/malformed.

        Returns `(tg_user_id, fingerprint)`. Validates the fingerprint shape so a
        poisoned payload can never reach `revive_slot`. The signal NEVER carries a
        session string — only the non-secret slot identity (defense-in-depth check)."""
        if self._redis is None:
            return None
        try:
            raw = cast("bytes | str | None", self._redis.get(POOL_REVIVE_SIGNAL_REDIS_KEY))
        except RedisError:
            return None
        if raw is None:
            return None
        text = raw if isinstance(raw, str) else raw.decode("utf-8")
        try:
            payload = json.loads(text)
        except (ValueError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        tg_user_id = payload.get("tg_user_id")
        fingerprint = payload.get("fingerprint", "")
        if not isinstance(tg_user_id, int) or not isinstance(fingerprint, str):
            return None
        if fingerprint and not _is_valid_fingerprint(fingerprint):
            return None
        return tg_user_id, fingerprint

    def _clear_revive_signal(self) -> None:
        """Delete the revive-signal so it applies once; best-effort, never raises."""
        if self._redis is None:
            return
        try:
            self._redis.delete(POOL_REVIVE_SIGNAL_REDIS_KEY)
        except RedisError:
            logger.warning("could not clear pool revive signal (Redis); ignoring")

    def _load_stored_session(self, tg_user_id: int) -> "StoredSession | None":
        """Load the NEW session for `tg_user_id` from the encrypted DB store (TASK-119).

        The secret is read from the DB (Fernet-decrypted at ORM read) inside the worker
        — it never travels through Redis. Opens a short-lived session via the storage
        unit-of-work. Returns None if no active row exists (revoked between signal+tick).
        """
        from storage.database import get_session
        from storage.pool_session_store import find_active_by_tg_user_id

        with get_session() as db:
            return find_active_by_tg_user_id(db, tg_user_id)

    def _quarantine_dead_account(self, exc: BaseException) -> None:
        """Evict the current account on a PERMANENT auth failure and alert ops ONCE.

        A permanent auth error (AuthKeyDuplicated/AuthKeyError/UserDeactivated/
        SessionRevoked) means the session string is dead forever — retrying re-reads
        the same dead session every tick (the prod alert-spam root cause, TASK-087).
        We quarantine the account so the pool never hands it out again (the durable,
        Redis-independent dedup) and send EXACTLY ONE ops alert keyed per account
        (`auth_dead:{n}`) so the owner re-mints that session. The fingerprint `n` is
        the account's pool index — NEVER a session string/secret.
        """
        # Record the dead-session reason on the CURRENT account BEFORE quarantine
        # rotates the index (TASK-115) — the error CLASS NAME, never a secret.
        self._pool.note_current_error(type(exc).__name__)
        fingerprint = self._pool.quarantine_current()
        self._emit_health_best_effort(
            notify_reason=f"auth_dead:{fingerprint}",
            notify_text=(
                f"TG pool: сессия #{fingerprint} мертва ({type(exc).__name__}) — "
                "аккаунт выселен из пула, перевыпусти сессию."
            ),
            emit_metric=False,
        )

    async def aclose(self) -> None:
        """Disconnect all pool clients — call on worker shutdown so MTProto
        connections aren't leaked across the worker's lifetime."""
        await self._pool.aclose()

    async def __aenter__(self) -> "TelegramCollector":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def validate_ref(self, ref: SourceRef) -> bool:
        """True iff `ref` is a readable public channel; never raises outward (AC2)."""
        if ref.kind is not SourceKind.TELEGRAM:
            return False
        handle = normalize_handle(ref.handle, ref.kind)
        try:
            client = self._pool.acquire()
            await _ensure_connected(client)
            await client.get_entity(handle)
        except AllAccountsFloodWaitError:
            # Transient pool exhaustion — cannot confirm, treat as not-validated now.
            return False
        except Exception:
            # Private / nonexistent / invalid handle, or network: not a public ref.
            # We intentionally catch broadly here BUT never re-raise (AC2 contract).
            logger.info("validate_ref rejected handle (not a public channel)")
            return False
        return True

    async def read(self, refs: list[SourceRef], since: datetime | None) -> AsyncIterator[RawPost]:
        """Yield `RawPost`s for the unique union of `refs` newer than `since` (AC5).

        Emits a single pool health metric + degraded self-alert once per read()
        invocation — after all channels have been processed (TASK-035: periodic
        svodka, no new Beat schedule — uses existing read loop).

        NOTE (TASK-119): the single-slot revive-signal check is NOT applied here — the
        collect tick calls `apply_pending_revive()` ONCE per cycle before its per-ref
        `read()` loop, so the revive GET is a single Redis read per tick (not per ref).
        The disconnect-before-connect single-slot revive invariant is unchanged.
        """
        for ref in unique_refs(refs):
            async for post in self._read_one(ref, since):
                yield post
            await self._sleep(INTER_REQUEST_SLEEP_SECONDS)
        # Single periodic health summary per read() cycle — best-effort, never
        # raises (Invariant). Placed after the loop so it fires once regardless
        # of how many channels are in `refs`.
        self._emit_health_best_effort()

    async def _read_one(self, ref: SourceRef, since: datetime | None) -> AsyncIterator[RawPost]:
        """Read a single channel once, with FLOOD_WAIT backoff + rotation (AC4).

        A FLOOD_WAIT hint is slept in-task only when short (<= the inline cap);
        a long hint marks the account cooling and retries through
        `_acquire_ready_client`, which rotates to a READY account or aborts the
        ref with `AllAccountsFloodWaitError` (pool=1: the "next" account IS the
        cooling one — sleeping the full hint here parked the collect tick on a
        celery slot for the FLOOD_WAIT's lifetime, the prod hang).

        Auth/ban exceptions (non-flood, non-source-unavailable) trigger a best-effort
        ops self-alert (TASK-035) before re-raising as SourceUnavailableError.
        """
        client = await self._acquire_ready_client(ref.handle)
        try:
            entity = await client.get_entity(ref.handle)
        except Exception as exc:
            if (wait := _flood_wait_seconds(exc)) is not None:
                # Record the reason on the CURRENT account before report_flood_wait
                # rotates the index (TASK-115) — annotation only, no behaviour change.
                self._pool.note_current_error("FLOOD_WAIT")
                self._pool.report_flood_wait(retry_after_seconds=wait)
                if wait <= FLOOD_WAIT_INLINE_CAP_SECONDS:
                    await self._sleep(wait)
                async for post in self._read_one(ref, since):
                    yield post
                return
            # PERMANENT auth failure (dead session) — quarantine the account so the
            # pool never re-reads it, alert ops ONCE, then skip the ref (TASK-087).
            if is_permanent_auth_error(exc):
                self._quarantine_dead_account(exc)
                raise SourceUnavailableError(
                    f"telegram account quarantined (permanent auth error) reading {ref.handle}"
                ) from exc
            # Non-flood TRANSIENT error on entity resolve (network/private, or the
            # swallowed "wrong session ID" class) — record a READ FAILURE on the current
            # account (TASK-118) so a persistently-failing-but-connected account is
            # surfaced as `failing` instead of staying `healthy` forever. The reason is
            # the error CLASS NAME, never a session string. Then notify ops (throttled)
            # and keep the account (it may recover next tick) — rotation UNCHANGED.
            self._pool.note_read_failure(type(exc).__name__)
            self._emit_health_best_effort(
                notify_reason="auth_error",
                notify_text=(f"TG pool: account error on entity resolve ({type(exc).__name__})"),
                emit_metric=False,
            )
            raise SourceUnavailableError(f"cannot resolve telegram ref {ref.handle}") from exc

        try:
            # Fetch the NEWEST posts in the recent window — newest-first, bounded
            # (task-078/task-083). Telethon's `iter_messages` default order is
            # newest→oldest (`reverse=False`); we walk from the top and BREAK as
            # soon as we pass `since`, so we read only the recent tail and stop.
            #
            # Why not `offset_date` + `reverse`? Both prior idioms were traps:
            #   * `reverse=False` + `offset_date=since`: `offset_date` is an
            #     EXCLUSIVE UPPER bound ("messages *previous* to this date"), so
            #     it walked the ENTIRE history backward (task-077: prod 2026→2017
            #     → GetHistory flood storms, 100k+ buffers, lock held full TTL).
            #   * `reverse=True` + `offset_date=since`: lower bound, oldest→newest
            #     — but it yields the OLDEST of the window first, so the cap
            #     truncates the NEWEST posts (wrong end for a viral detector); and
            #     when the marker is absent (Redis flush → `_init` forces
            #     `offset_id = 1`) it returns the channel's OLDEST messages
            #     forward (task-083 prod launch bug: ingested 2024-era posts).
            #
            # Newest-first + early break + `limit=MAX_MESSAGES_PER_TICK` keeps the
            # NEWEST posts, never deep-pulls, and is correct even with no marker
            # (`since = now - collect_lookback_seconds`, never None at the tick).
            # The `limit` is the hard backstop if `since` is misconfigured/absent.
            async for message in client.iter_messages(
                entity,
                reverse=False,
                limit=MAX_MESSAGES_PER_TICK,
            ):
                # Newest→oldest: the first message older than `since` means every
                # later one is older too — stop the scan (don't merely skip).
                if since is not None and message.date is not None and message.date < since:
                    break
                yield map_entity(message, ref)
            self._pool.report_success()
            # Record a CLEAN read outcome on the current account (TASK-118): resets the
            # consecutive-failure counter + stamps last_read_ok_at so a recovered account
            # leaves `failing`. Annotation only — no rotation/cooldown change.
            self._pool.note_read_success()
        except Exception as exc:
            if (wait := _flood_wait_seconds(exc)) is not None:
                # Record the reason on the CURRENT account before report_flood_wait
                # rotates the index (TASK-115) — annotation only, no behaviour change.
                self._pool.note_current_error("FLOOD_WAIT")
                self._pool.report_flood_wait(retry_after_seconds=wait)
                if wait <= FLOOD_WAIT_INLINE_CAP_SECONDS:
                    await self._sleep(wait)
                async for post in self._read_one(ref, since):
                    yield post
                return
            # A permanent auth error can also surface mid-iteration — quarantine
            # the dead account here too (TASK-087), alert once, then skip the ref.
            if is_permanent_auth_error(exc):
                self._quarantine_dead_account(exc)
                raise SourceUnavailableError(
                    f"telegram account quarantined (permanent auth error) reading {ref.handle}"
                ) from exc
            # Non-flood TRANSIENT error mid-iteration (the swallowed "wrong session ID"
            # class can surface here too) — record a READ FAILURE on the current account
            # (TASK-118), class name only, then skip the ref. Rotation UNCHANGED.
            self._pool.note_read_failure(type(exc).__name__)
            raise SourceUnavailableError(f"failed reading telegram ref {ref.handle}") from exc

    async def _acquire_ready_client(self, handle: str) -> TelegramClientProtocol:
        """Acquire an account for ``handle`` with deterministic slot affinity (TASK-131).

        Uses ``self._pool.acquire_for_channel(handle)`` so a given channel is
        preferentially read by a STABLE healthy slot (``pick_slot_for_channel`` =
        sha256(handle) % healthy_count) — this spreads load across the pool and cuts
        per-account FLOOD_WAIT instead of every channel contending on one rotation.
        When the mapped slot is cooling/quarantined ``acquire_for_channel`` FALLS BACK
        to ``acquire()`` rotation, raising the IDENTICAL ``PoolExhaustedError`` /
        ``AllAccountsFloodWaitError`` it does today — so rotation, backoff and
        quarantine semantics are preserved exactly (the affinity only changes WHICH
        healthy slot is tried first). The ``handle`` is threaded from ``_read_one``
        via ``ref.handle``.

        On AllAccountsFloodWaitError a cooldown within the inline cap is slept
        and retried; a longer cooldown RE-RAISES so the caller skips the ref
        (collect tick logs "source skipped" and moves on) instead of holding the
        task coroutine for the cooldown's lifetime. Pool health metric + ops
        self-alert (TASK-035) are emitted best-effort either way.
        """
        while True:
            try:
                client = self._pool.acquire_for_channel(handle)
            except PoolExhaustedError:
                # Every session is dead/quarantined → ingest is fully stopped. The
                # per-account `auth_dead:{n}` alert fired ONCE at quarantine time; this
                # REPEATING (throttled, ~hourly) alert re-nudges the owner to re-mint
                # sessions so a missed one-shot doesn't mean weeks of silent downtime.
                # Re-raise so the caller skips the ref (unchanged behavior).
                self._emit_health_best_effort(
                    notify_reason="pool_exhausted",
                    notify_text=(
                        "TG pool fully exhausted - all sessions dead/quarantined; "
                        "ingest is stopped. Re-mint Telegram sessions."
                    ),
                    emit_metric=False,
                )
                raise
            except AllAccountsFloodWaitError:
                wait = self._pool.cooldown_remaining()
                # Best-effort health metric + ops self-alert (TASK-035, Invariant).
                self._emit_health_best_effort(
                    notify_reason="all_flood",
                    notify_text=(f"TG pool: all accounts flooded. cooldown_remaining={int(wait)}s"),
                    emit_metric=False,
                )
                if wait > FLOOD_WAIT_INLINE_CAP_SECONDS:
                    raise
                await self._sleep(wait)
                continue
            await _ensure_connected(client)
            return client
