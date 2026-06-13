"""Thin typed interface over a Telethon client + a factory (AC8, testability).

The reader/pool depend ONLY on `TelegramClientProtocol`, never on the concrete
`TelegramClient` constructor — so unit tests inject a mock client (no network, no
real sessions) while production wires the real Telethon client via
`build_telethon_client`. Session strings are pool technical-account creds from env;
there is NO user `session_string` concept anywhere (overview §2/§7).
"""

from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Protocol, cast

from collector.telegram.mapper import TelegramMessage


class TelegramEntityProtocol(Protocol):
    """Marker for a resolved Telethon entity (channel/user)."""


class TelegramClientProtocol(Protocol):
    """The minimal Telethon surface the pool/reader use.

    `iter_messages` yields `TelegramMessage` — the exact structural shape the pure
    `map_entity` consumes — so no `Any` crosses the transport→mapper boundary.
    """

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    def is_connected(self) -> bool: ...

    async def get_entity(self, handle: str) -> TelegramEntityProtocol: ...

    def iter_messages(
        self,
        entity: TelegramEntityProtocol,
        *,
        offset_date: datetime | None = None,
        reverse: bool = False,
        limit: int | None = None,
    ) -> AsyncIterator[TelegramMessage]: ...


# A factory builds a (disconnected) client for one pool session string.
TelegramClientFactory = Callable[[str], TelegramClientProtocol]


def build_telethon_client(*, api_id: int, api_hash: str) -> TelegramClientFactory:
    """Return a factory that builds a real Telethon client from a pool session string.

    telethon is imported lazily inside so that importing this module (and the
    collector package) never requires telethon in pure-unit contexts.
    """

    def _factory(session: str) -> TelegramClientProtocol:
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        client = TelegramClient(StringSession(session), api_id, api_hash)
        # telethon is untyped (mypy override) → the constructor is `Any`; pin it to
        # our structural protocol at this single boundary instead of leaking `Any`.
        return cast(TelegramClientProtocol, client)

    return _factory
