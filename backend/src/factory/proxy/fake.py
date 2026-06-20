"""Deterministic in-memory `ProxyProvider` (TASK-139, CI-safe, no network).

`allocate` builds a deterministic `socks5://user:pass@host:port` lease from the
`FAKE_PROXY_*` fixtures plus a monotonic counter (so allocate is deterministic but
lease ids are unique within an instance). `release` records the id in `released_ids`
and never raises (so TASK-140's integration test can assert the release happened).
`balance` returns a constant `Decimal`. No sleeps, no I/O.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from factory.constants import (
    FAKE_PROXY_DEFAULT_BALANCE,
    FAKE_PROXY_HOST,
    FAKE_PROXY_LEASE_ID_PREFIX,
    FAKE_PROXY_LOGIN,
    FAKE_PROXY_PASSWORD,
    FAKE_PROXY_PORT,
    FAKE_PROXY_SCHEME,
)
from factory.proxy.base import ProxyLease

_BALANCE_DEFAULT = Decimal(FAKE_PROXY_DEFAULT_BALANCE)


class FakeProxyProvider:
    """A scripted `ProxyProvider` for tests (structurally satisfies the Protocol)."""

    def __init__(
        self,
        *,
        balance: Decimal = _BALANCE_DEFAULT,
        expires_at: datetime | None = None,
    ) -> None:
        self._balance = balance
        self._expires_at = expires_at
        self._counter = 0
        # Released lease ids — exposed so TASK-140's integration test can assert the
        # release happened. A set: re-releasing the same id is idempotent.
        self.released_ids: set[str] = set()

    async def allocate(self, country: str | None) -> ProxyLease:
        self._counter += 1
        lease_id = f"{FAKE_PROXY_LEASE_ID_PREFIX}{self._counter}"
        uri = (
            f"{FAKE_PROXY_SCHEME}://{FAKE_PROXY_LOGIN}:{FAKE_PROXY_PASSWORD}"
            f"@{FAKE_PROXY_HOST}:{FAKE_PROXY_PORT}"
        )
        return ProxyLease(
            lease_id=lease_id,
            uri=uri,
            country=country,
            expires_at=self._expires_at,
        )

    async def release(self, lease_id: str) -> None:
        # Best-effort + idempotent: record the id and never raise (mirrors the contract).
        self.released_ids.add(lease_id)
        return None

    async def balance(self) -> Decimal:
        return self._balance

    async def aclose(self) -> None:
        """No-op — the fake holds no transport resources."""
        return None
