"""The `ProxyProvider` interface + `ProxyLease` DTO (TASK-139, testability).

Mirrors the `SmsProvider` abstraction (TASK-133): the factory loop (TASK-140) depends
ONLY on `ProxyProvider` — never on httpx or Mobileproxy.space — so unit tests inject
`FakeProxyProvider` (no network) while production wires `MobileProxyProvider`. Money is
`Decimal` (never float — budget-accounting precision). The proxy `uri` is a SECRET.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ProxyLease:
    """A proxy port allocated from a provider: its opaque port id + the SOCKS5 uri.

    `lease_id` is the provider's opaque port id (non-secret) — used by `release` and
    persisted so a later beat can release the port. `uri`
    (`socks5://user:pass@host:port`) carries the proxy creds and is a SECRET — NEVER
    logged or echoed in an error. `country` is the requested geo (or `None` = any).
    `expires_at` is the provider-reported rental end (or `None` if not reported).
    """

    lease_id: str
    uri: str
    country: str | None
    expires_at: datetime | None


@runtime_checkable
class ProxyProvider(Protocol):
    """Minimal dynamic-proxy surface the factory uses (allocate → use → release).

    Non-OK upstream responses are mapped to typed `ProxyProviderError` subclasses — the
    interface never returns sentinel error values or leaks the transport's exceptions.
    `release` is best-effort and NEVER raises (releasing a dead proxy must not mask the
    surrounding registration outcome). There is intentionally NO `rotate` — stickiness
    is the invariant (a rotated IP would break a logged-in session).
    """

    async def allocate(self, country: str | None) -> ProxyLease:
        """Allocate a sticky SOCKS5 proxy in `country` (or any if `None`)."""
        ...

    async def release(self, lease_id: str) -> None:
        """Release the port for `lease_id` (best-effort — never raises)."""
        ...

    async def balance(self) -> Decimal:
        """Return the account balance (provider currency) as a `Decimal`."""
        ...

    async def aclose(self) -> None:
        """Release transport resources (best-effort)."""
        ...
