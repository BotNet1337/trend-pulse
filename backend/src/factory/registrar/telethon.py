"""Real Telethon-backed `TelegramRegistrar` (TASK-133, config-gated).

This is the production registration path: connect → `send_code_request` → fetch the
SMS code via `code_cb` → `sign_in`; if the number has no account yet
(`PhoneNumberUnoccupied`, the expected case for a freshly-bought number) → `sign_up`
to CREATE the account. Returns the new account's `StringSession` + `tg_user_id`. It is
selected ONLY when telegram api creds are configured and never
runs in CI/this env (no telethon-network test). telethon is imported lazily inside
`register` so importing this module never requires telethon.

Both the proxy URI and the session string are SECRETS — never logged here.
"""

from __future__ import annotations

from typing import Protocol, cast

from factory.constants import FACTORY_SIGNUP_FIRST_NAMES, FACTORY_SIGNUP_LAST_NAME
from factory.errors import RegistrarBannedError, RegistrarPasswordNeededError
from factory.registrar.base import CodeCallback, RegisteredSession


def pick_signup_first_name(phone: str) -> str:
    """Deterministically pick a cosmetic first name for a NEW-account sign_up.

    Indexed by the number's digits so a retry of the SAME phone yields the SAME name
    (no randomness — stable across processes). Names are cosmetic per the owner.
    """
    digits = sum(int(c) for c in phone if c.isdigit())
    return FACTORY_SIGNUP_FIRST_NAMES[digits % len(FACTORY_SIGNUP_FIRST_NAMES)]


class _TelethonClientProtocol(Protocol):
    """The minimal Telethon surface used here — pins `Any` at the single boundary."""

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def send_code_request(self, phone: str) -> object: ...

    async def sign_in(self, phone: str, code: str) -> object: ...

    async def sign_up(self, code: str, first_name: str, last_name: str) -> object: ...

    async def get_me(self) -> _MeProtocol: ...


class _MeProtocol(Protocol):
    """The slice of the Telethon `User` entity we read (`id`)."""

    id: int


class TelethonRegistrar:
    """Registers a phone on Telegram via Telethon and returns its session."""

    def __init__(self, *, api_id: int, api_hash: str) -> None:
        self._api_id = api_id
        self._api_hash = api_hash

    async def register(
        self, *, phone: str, code_cb: CodeCallback, proxy: str | None = None
    ) -> RegisteredSession:
        # Lazy imports — keep telethon off the import path for pure-unit contexts.
        from telethon import TelegramClient
        from telethon.errors import (
            PhoneNumberBannedError,
            PhoneNumberUnoccupiedError,
            SessionPasswordNeededError,
        )
        from telethon.sessions import StringSession

        # Reuse the collector's proxy-parse seam (public fn) so SOCKS5 handling is
        # identical to the live pool; the proxy URI is a secret and is never logged.
        if proxy is not None:
            from collector.telegram.client import parse_socks5_proxy

            proxy_tuple = parse_socks5_proxy(proxy)
            raw_client = TelegramClient(
                StringSession(), self._api_id, self._api_hash, proxy=proxy_tuple
            )
        else:
            raw_client = TelegramClient(StringSession(), self._api_id, self._api_hash)
        # telethon is untyped (mypy override) → constructor is `Any`; pin it to our
        # structural protocol at this single boundary instead of leaking `Any`.
        client = cast(_TelethonClientProtocol, raw_client)

        await client.connect()
        try:
            await client.send_code_request(phone)
            code = await code_cb()
            try:
                await client.sign_in(phone, code)
            except PhoneNumberUnoccupiedError:
                # The number has no account yet (the expected path for a freshly-bought
                # number) → CREATE a new account. This is what makes the factory actually
                # REGISTER (not just log in). Name is cosmetic + deterministic per phone.
                await client.sign_up(code, pick_signup_first_name(phone), FACTORY_SIGNUP_LAST_NAME)
            except SessionPasswordNeededError as exc:
                raise RegistrarPasswordNeededError(
                    "telegram requires 2FA password (SESSION_PASSWORD_NEEDED)"
                ) from exc
            except PhoneNumberBannedError as exc:
                raise RegistrarBannedError(
                    "telegram banned this phone number (PHONE_NUMBER_BANNED)"
                ) from exc
            me = await client.get_me()
            session_string = cast(str, StringSession.save(raw_client.session))
            return RegisteredSession(session_string=session_string, tg_user_id=me.id)
        finally:
            await client.disconnect()
