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

    def __repr__(self) -> str:
        """Mask the secret `uri` (user:pass creds) in any repr/str/log output.

        The dataclass auto-`__repr__` would echo the full `socks5://user:pass@host:port`
        — a creds leak the moment a `ProxyLease` lands in a log line or an exception repr.
        We show ONLY the scheme (everything after `://` is masked, so neither host nor
        user:pass appears); `lease_id`/`country`/`expires_at` stay visible (non-secret).
        """
        scheme, sep, _ = self.uri.partition("://")
        masked_uri = f"{scheme}://***" if sep else "***"
        return (
            f"ProxyLease(lease_id={self.lease_id!r}, uri={masked_uri!r}, "
            f"country={self.country!r}, expires_at={self.expires_at!r})"
        )


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
