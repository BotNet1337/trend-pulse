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
from urllib.parse import unquote, urlparse

from collector.constants import SOCKS5_DEFAULT_PORT, SOCKS5_PROXY_TYPE
from collector.errors import InvalidProxyError
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


# A factory builds a (disconnected) client for one pool session string plus an
# optional SOCKS5 proxy URI (TASK-129). The proxy is an opaque secret — the
# factory is responsible for never logging it.
TelegramClientFactory = Callable[[str, "str | None"], TelegramClientProtocol]


def parse_socks5_proxy(uri: str) -> tuple[int, str, int, bool, str | None, str | None]:
    """Parse a SOCKS5 proxy URI into Telethon's proxy tuple (TASK-129).

    Accepts: `socks5://[user:pass@]host[:port]`

    Returns: `(SOCKS5_PROXY_TYPE, host, port, rdns=True, username, password)`

    The return type matches what `TelegramClient(..., proxy=<tuple>)` accepts.
    Telethon interprets the integer 2 as SOCKS5 — the same numeric value used by
    both PySocks (`socks.SOCKS5 == 2`) and python-socks (`ProxyType.SOCKS5 == 2`);
    no import of either library is required here. `rdns=True` means DNS resolution
    happens on the proxy side, which is the correct default for privacy and
    compatibility.

    Raises `InvalidProxyError` for:
      - wrong scheme (not "socks5")
      - missing host

    The error message NEVER includes user:pass credentials from the URI — only
    the scheme/host problem is described.

    Missing port → `SOCKS5_DEFAULT_PORT`.
    No auth credentials → username and password are None.
    """
    parsed = urlparse(uri)

    if parsed.scheme != "socks5":
        raise InvalidProxyError(
            f"invalid SOCKS5 proxy: expected scheme 'socks5', got '{parsed.scheme}'"
        )

    host = parsed.hostname
    if not host:
        raise InvalidProxyError("invalid SOCKS5 proxy: host is missing or empty")

    # FIX 1: urlparse raises ValueError for out-of-range (>65535) or non-numeric ports.
    # Re-raise as InvalidProxyError with a CREDENTIAL-FREE message so the pool builder
    # catches it per-slot (AC3) and never leaks user:pass from the URI.
    try:
        port: int = parsed.port if parsed.port is not None else SOCKS5_DEFAULT_PORT
    except ValueError:
        raise InvalidProxyError(
            "invalid SOCKS5 proxy: port is out of range or non-numeric"
        ) from None

    # FIX 3: urlparse does NOT percent-decode userinfo; apply unquote so a password like
    # p%40ss is handed to Telethon as the literal p@ss that the proxy server expects.
    raw_username: str | None = parsed.username or None
    raw_password: str | None = parsed.password or None
    username: str | None = unquote(raw_username) if raw_username is not None else None
    password: str | None = unquote(raw_password) if raw_password is not None else None

    return (SOCKS5_PROXY_TYPE, host, port, True, username, password)


def build_telethon_client(*, api_id: int, api_hash: str) -> TelegramClientFactory:
    """Return a factory that builds a real Telethon client from a pool session string.

    The factory accepts an optional `proxy` URI (TASK-129). When `proxy` is not None,
    `parse_socks5_proxy` converts it to a PySocks tuple and passes it to
    `TelegramClient(..., proxy=...)`. When None, the client is constructed exactly as
    today — byte-identical path, no proxy kwarg.

    A parse failure (`InvalidProxyError`) propagates so `AccountPool.from_sessions`
    can catch it per-slot and skip only that slot (fail-closed for the one slot,
    fail-open for the rest of the pool).

    telethon is imported lazily inside so that importing this module (and the
    collector package) never requires telethon in pure-unit contexts.

    The proxy string is a SECRET — it carries user:pass credentials and is NEVER
    logged here or anywhere in this module.
    """

    def _factory(session: str, proxy: str | None = None) -> TelegramClientProtocol:
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        if proxy is not None:
            # parse_socks5_proxy raises InvalidProxyError on bad input; the pool
            # builder catches it per-slot so the error propagates cleanly.
            proxy_tuple = parse_socks5_proxy(proxy)
            client = TelegramClient(StringSession(session), api_id, api_hash, proxy=proxy_tuple)
        else:
            client = TelegramClient(StringSession(session), api_id, api_hash)
        # telethon is untyped (mypy override) → the constructor is `Any`; pin it to
        # our structural protocol at this single boundary instead of leaking `Any`.
        return cast(TelegramClientProtocol, client)

    return _factory
