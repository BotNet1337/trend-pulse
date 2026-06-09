"""Pool of technical Telegram accounts with FLOOD_WAIT rotation (AC4, AC8).

Each account is one pool StringSession (env: TELEGRAM_POOL_SESSIONS) sharing the
api_id/api_hash. The pool picks an active (not cooling-down) account; on a
FLOOD_WAIT it marks that account cooling-down with exponential backoff and rotates
to the next. When every account is cooling down it raises
`AllAccountsFloodWaitError` so the caller backs off (never crashes the collector).

Secrets (session strings, api_hash) are stored but NEVER logged. There is no user
`session_string` concept — only pool technical accounts (overview §2/§7).
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from collector.constants import (
    BACKOFF_BASE_SECONDS,
    BACKOFF_CAP_SECONDS,
    POOL_MAX,
    POOL_MIN,
)
from collector.errors import AllAccountsFloodWaitError, PoolConfigError
from collector.telegram.client import TelegramClientFactory, TelegramClientProtocol

logger = logging.getLogger(__name__)


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

    @classmethod
    def from_sessions(
        cls,
        *,
        sessions: list[str],
        factory: TelegramClientFactory,
    ) -> "AccountPool":
        """Build a pool from pool session strings; validates size POOL_MIN..POOL_MAX."""
        size = len(sessions)
        if size < POOL_MIN or size > POOL_MAX:
            raise PoolConfigError(
                f"telegram pool must have between {POOL_MIN} and {POOL_MAX} "
                f"technical accounts, got {size}"
            )
        accounts = [_Account(client=factory(session)) for session in sessions]
        return cls(_accounts=accounts)

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
        """Number of accounts currently in cooldown (read-only, no behaviour change)."""
        now = self._clock()
        return sum(1 for a in self._accounts if a.cooldown_until > now)

    def acquire(self) -> TelegramClientProtocol:
        """Return the client of the next account that is not cooling down.

        Raises `AllAccountsFloodWaitError` when every account is cooling down.
        """
        if not self._accounts:
            raise PoolConfigError("account pool is empty")
        now = self._clock()
        count = len(self._accounts)
        for offset in range(count):
            idx = (self._index + offset) % count
            account = self._accounts[idx]
            if account.cooldown_until <= now:
                self._index = idx
                return account.client
        raise AllAccountsFloodWaitError("all pool accounts are cooling down under FLOOD_WAIT")

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
        """Smallest remaining cooldown across all accounts (seconds); 0 if any ready."""
        now = self._clock()
        remaining = [max(0.0, a.cooldown_until - now) for a in self._accounts]
        ready = [r for r in remaining if r <= 0.0]
        if ready:
            return 0.0
        return min(remaining) if remaining else 0.0

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
