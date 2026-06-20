"""The `HealthProbe` interface + `HealthResult` DTO (TASK-141, testability).

The factory loop (`_promote_phase`) depends ONLY on `HealthProbe` — never on Telethon
— so unit/integration tests inject `FakeHealthProbe` (no network) while production
wires `TelethonHealthProbe`. A probe reads a public channel through the account's OWN
session + proxy and reports whether the read succeeded; the session string and proxy
URI are SECRETS and are NEVER carried in the result `reason` (a class name only).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class HealthResult:
    """The outcome of a pre-promote health probe.

    `ok` is True iff the account read ≥1 message from the public channel over its own
    session+proxy. `reason` is a SHORT non-secret diagnostic (an exception class name)
    on failure, or `None` on success — it MUST NEVER include the session string or the
    proxy URI (both secrets).
    """

    ok: bool
    reason: str | None


@runtime_checkable
class HealthProbe(Protocol):
    """Read a public channel through an account's session+proxy (TASK-141)."""

    async def check(self, *, session_string: str, proxy: str | None) -> HealthResult:
        """Probe `session_string` over `proxy` (a SOCKS5 URI or None — both SECRETS).

        Returns `HealthResult(ok=True, reason=None)` when the account can read the
        configured public channel; otherwise `ok=False` with a non-secret class-name
        `reason`. NEVER raises (failure is reported, not thrown) and NEVER logs/echoes
        the session string or proxy URI.
        """
        ...
