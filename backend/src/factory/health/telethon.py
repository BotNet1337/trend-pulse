"""Real Telethon-backed `HealthProbe` (TASK-141, config-gated).

The production pre-promote gate: connect the account's OWN `StringSession` OVER its
sticky proxy → resolve a known public channel → read ≥1 message. `ok=True` iff a
message is read. This authenticated read over the sticky proxy IS the light warm-up
(a gentle action; a richer multi-day warming schedule is a documented follow-up). It
is selected ONLY when telegram creds + a real provider + a probe channel are all set
and never runs over the network in CI; telethon is imported lazily inside `check`.

Both the proxy URI and the session string are SECRETS — never logged here, and never
carried in a `HealthResult.reason` (the reason is an exception CLASS NAME only). The
client is ALWAYS disconnected (finally), and `check` NEVER raises (failure is mapped
to `ok=False`) so the promote phase can off-ramp the row without crashing the tick.
"""

from __future__ import annotations

import contextlib
from typing import Protocol, cast

from factory.health.base import HealthResult


class _TelethonClientProtocol(Protocol):
    """The minimal Telethon surface used here — pins `Any` at the single boundary."""

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def get_entity(self, entity: str) -> object: ...

    async def get_messages(self, entity: str, limit: int) -> object: ...


class TelethonHealthProbe:
    """Reads a public channel through an account's session+proxy via Telethon."""

    def __init__(self, *, api_id: int, api_hash: str, channel: str, read_limit: int) -> None:
        self._api_id = api_id
        self._api_hash = api_hash
        self._channel = channel
        self._read_limit = read_limit

    async def check(self, *, session_string: str, proxy: str | None) -> HealthResult:
        # Lazy imports — keep telethon off the import path for pure-unit contexts.
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        if proxy is not None:
            # Reuse the collector's proxy-parse seam so SOCKS5 handling is identical to
            # the live pool; the proxy URI is a secret and is never logged.
            from collector.telegram.client import parse_socks5_proxy

            raw_client = TelegramClient(
                StringSession(session_string),
                self._api_id,
                self._api_hash,
                proxy=parse_socks5_proxy(proxy),
            )
        else:
            raw_client = TelegramClient(StringSession(session_string), self._api_id, self._api_hash)
        # telethon is untyped (mypy override) → constructor is `Any`; pin it to our
        # structural protocol at this single boundary instead of leaking `Any`.
        client = cast(_TelethonClientProtocol, raw_client)

        connected = False
        try:
            await client.connect()
            connected = True
            # Resolve the channel then read ≥1 message — the honest "can-read" gate.
            await client.get_entity(self._channel)
            messages = await client.get_messages(self._channel, self._read_limit)
            ok = _has_message(messages)
            return HealthResult(ok=ok, reason=None if ok else "no-messages")
        except Exception as exc:
            # NEVER echo the session string or proxy URI — only the exception class name
            # (no `str(exc)`, which could embed a secret from a wrapped transport error).
            return HealthResult(ok=False, reason=type(exc).__name__)
        finally:
            if connected:
                # Always disconnect (no leaked client / live co-connection). Best-effort:
                # a disconnect blip must not mask the probe outcome (already set).
                with contextlib.suppress(Exception):
                    await client.disconnect()


def _has_message(messages: object) -> bool:
    """True iff the `get_messages` result carries ≥1 message (length-checked, no secret)."""
    try:
        return len(cast("list[object]", messages)) >= 1
    except TypeError:
        # A non-sized result (defensive) → treat as no readable messages.
        return False
