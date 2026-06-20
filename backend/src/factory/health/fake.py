"""Deterministic in-memory `HealthProbe` (TASK-141, CI-safe, no network).

Returns a scripted `HealthResult` without touching Telegram, so the factory promote
gate is exercised end-to-end in tests (and on the fake/offline path) without a network
read. Selected by `get_health_probe` whenever the real probe is not fully configured.
"""

from __future__ import annotations

from factory.health.base import HealthResult


class FakeHealthProbe:
    """A scripted `HealthProbe` for tests (structurally satisfies the Protocol).

    `ok=True` (the default) → a deterministic pass; `ok=False` → a deterministic fail
    with a fixed non-secret reason. Never reads the session string or proxy URI.
    """

    def __init__(self, ok: bool = True) -> None:
        self._ok = ok

    async def check(self, *, session_string: str, proxy: str | None) -> HealthResult:
        return HealthResult(ok=self._ok, reason=None if self._ok else "fake-probe-fail")
