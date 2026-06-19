"""The `TelegramRegistrar` interface + DTO (TASK-133, testability).

The factory loop (TASK-134) depends ONLY on `TelegramRegistrar` — never on Telethon
— so unit tests inject `FakeRegistrar` (no network) while production wires
`TelethonRegistrar`. The code is delivered asynchronously by `code_cb` (the SMS
provider's `poll_code`), so the callback is awaitable to match that flow.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# An async callback that yields the SMS verification code when it arrives. It is
# awaitable because the real source (`SmsProvider.poll_code`) is itself async.
CodeCallback = Callable[[], Awaitable[str]]


@dataclass(frozen=True)
class RegisteredSession:
    """The result of a successful Telegram registration/login.

    `session_string` is a Telethon `StringSession` (a SECRET — never logged);
    `tg_user_id` is the numeric account id from `get_me()`.
    """

    session_string: str
    tg_user_id: int


@runtime_checkable
class TelegramRegistrar(Protocol):
    """Register/login a phone on Telegram and return its session (TASK-133)."""

    async def register(
        self, *, phone: str, code_cb: CodeCallback, proxy: str | None = None
    ) -> RegisteredSession:
        """Register `phone`, fetch the code via `code_cb`, return the session.

        `proxy` is an optional SOCKS5 URI (a SECRET — never logged). Raises
        `RegistrarBannedError` / `RegistrarPasswordNeededError` on the known failures.
        """
        ...
