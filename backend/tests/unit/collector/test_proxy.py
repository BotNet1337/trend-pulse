"""TASK-129 — proxy-per-session: parse_socks5_proxy + pool passthrough (TDD RED→GREEN).

Unit tests for:
  - parse_socks5_proxy: valid/no-auth/missing-port/invalid inputs
  - AC1: pool built with proxies=["socks5://u:p@h:1080", None] → slot0 client gets
    that proxy, slot1 gets None (via FakeClient.proxy capture)
  - AC2: all-None proxies → no proxy reaches factory (byte-identical path)
  - AC3: one bad proxy degrades exactly one slot (the bad slot is skipped, pool has 1 account)

Marker: unit.
"""

from __future__ import annotations

import pytest

from collector.constants import SOCKS5_DEFAULT_PORT, SOCKS5_PROXY_TYPE
from collector.errors import InvalidProxyError
from collector.telegram.account_pool import AccountPool
from collector.telegram.client import parse_socks5_proxy

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# parse_socks5_proxy — valid inputs
# ---------------------------------------------------------------------------


def test_parse_full_uri() -> None:
    """socks5://user:pass@host:9050 → correct tuple."""
    result = parse_socks5_proxy("socks5://user:pass@host:9050")
    assert result[0] == SOCKS5_PROXY_TYPE  # == 2 (Telethon integer convention)
    assert result[1] == "host"
    assert result[2] == 9050
    assert result[3] is True  # rdns=True
    assert result[4] == "user"
    assert result[5] == "pass"


def test_parse_no_auth() -> None:
    """socks5://host:1080 → username and password are None."""
    result = parse_socks5_proxy("socks5://host:1080")
    assert result[0] == SOCKS5_PROXY_TYPE
    assert result[1] == "host"
    assert result[2] == 1080
    assert result[3] is True
    assert result[4] is None
    assert result[5] is None


def test_parse_missing_port_uses_default() -> None:
    """socks5://host (no port) → SOCKS5_DEFAULT_PORT."""
    result = parse_socks5_proxy("socks5://host")
    assert result[0] == SOCKS5_PROXY_TYPE
    assert result[1] == "host"
    assert result[2] == SOCKS5_DEFAULT_PORT
    assert result[3] is True
    assert result[4] is None
    assert result[5] is None


def test_parse_with_auth_and_default_port() -> None:
    """socks5://user:pass@host (no port) → SOCKS5_DEFAULT_PORT, auth present."""
    result = parse_socks5_proxy("socks5://user:pass@host")
    assert result[1] == "host"
    assert result[2] == SOCKS5_DEFAULT_PORT
    assert result[4] == "user"
    assert result[5] == "pass"


# ---------------------------------------------------------------------------
# parse_socks5_proxy — invalid inputs → InvalidProxyError
# ---------------------------------------------------------------------------


def test_parse_empty_string_raises() -> None:
    with pytest.raises(InvalidProxyError):
        parse_socks5_proxy("")


def test_parse_wrong_scheme_raises() -> None:
    with pytest.raises(InvalidProxyError):
        parse_socks5_proxy("http://proxy.example.com:8080")


def test_parse_socks5_no_host_raises() -> None:
    """socks5:// with no host must raise."""
    with pytest.raises(InvalidProxyError):
        parse_socks5_proxy("socks5://")


def test_parse_random_garbage_raises() -> None:
    with pytest.raises(InvalidProxyError):
        parse_socks5_proxy("not-a-uri")


def test_parse_error_message_never_contains_credentials() -> None:
    """The error message must not echo user:pass credentials from the URI."""
    bad_uri = "http://secretuser:secretpass@host:1080"
    with pytest.raises(InvalidProxyError) as exc_info:
        parse_socks5_proxy(bad_uri)
    msg = str(exc_info.value)
    assert "secretuser" not in msg
    assert "secretpass" not in msg


# ---------------------------------------------------------------------------
# Proxy-capturing FakeClient helpers
# ---------------------------------------------------------------------------


class _ProxyCapturingClient:
    """Minimal fake client that captures the proxy kwarg passed at construction."""

    def __init__(self, *, proxy: str | None = None) -> None:
        self.proxy = proxy

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    def is_connected(self) -> bool:
        return False


def _make_proxy_pool(
    sessions: list[str],
    proxies: list[str | None],
) -> tuple[AccountPool, list[_ProxyCapturingClient]]:
    """Build a pool over _ProxyCapturingClient factories; return pool + clients."""
    clients: list[_ProxyCapturingClient] = []

    def factory(session: str, proxy: str | None = None) -> _ProxyCapturingClient:
        client = _ProxyCapturingClient(proxy=proxy)
        clients.append(client)
        return client

    pool = AccountPool.from_sessions(
        sessions=sessions,
        factory=factory,
        proxies=proxies,
    )
    return pool, clients


# ---------------------------------------------------------------------------
# AC1 — proxy is threaded through to the correct slot
# ---------------------------------------------------------------------------


def test_ac1_proxy_passed_to_factory_slot0() -> None:
    """AC1: slot with a valid proxy URI → factory receives that proxy string."""
    proxy_uri = "socks5://u:p@h:1080"
    pool, clients = _make_proxy_pool(
        sessions=["session-0", "session-1"],
        proxies=[proxy_uri, None],
    )
    assert len(pool) == 2
    assert clients[0].proxy == proxy_uri
    assert clients[1].proxy is None


def test_ac1_proxy_all_present() -> None:
    """All slots have proxies → each factory call receives the correct one."""
    proxies = ["socks5://u1:p1@h1:9050", "socks5://u2:p2@h2:9051"]
    _pool, clients = _make_proxy_pool(
        sessions=["session-0", "session-1"],
        proxies=proxies,
    )
    assert clients[0].proxy == proxies[0]
    assert clients[1].proxy == proxies[1]


# ---------------------------------------------------------------------------
# AC2 — no proxy configured → byte-identical path (no proxy in factory)
# ---------------------------------------------------------------------------


def test_ac2_no_proxy_none_list() -> None:
    """proxies=None (default) → factory receives proxy=None for every slot."""
    _pool, clients = _make_proxy_pool(
        sessions=["session-0", "session-1"],
        proxies=[None, None],
    )
    assert all(c.proxy is None for c in clients)


def test_ac2_no_proxy_default_argument() -> None:
    """from_sessions with no proxies kwarg → factory receives proxy=None."""
    clients_built: list[_ProxyCapturingClient] = []

    def factory(session: str, proxy: str | None = None) -> _ProxyCapturingClient:
        client = _ProxyCapturingClient(proxy=proxy)
        clients_built.append(client)
        return client

    AccountPool.from_sessions(sessions=["s0"], factory=factory)
    assert clients_built[0].proxy is None


# ---------------------------------------------------------------------------
# AC3 — one bad proxy degrades exactly one slot, pool still builds
# ---------------------------------------------------------------------------


def test_ac3_bad_proxy_skips_only_that_slot() -> None:
    """AC3: factory raises InvalidProxyError for slot0's proxy → slot0 skipped, slot1 builds."""
    _BAD_PROXY_SENTINEL = "__BAD__"
    built_sessions: list[str] = []

    def factory(session: str, proxy: str | None = None) -> _ProxyCapturingClient:
        if proxy == _BAD_PROXY_SENTINEL:
            raise InvalidProxyError("invalid SOCKS5 proxy: bad scheme")
        built_sessions.append(session)
        return _ProxyCapturingClient(proxy=proxy)

    pool = AccountPool.from_sessions(
        sessions=["session-0", "session-1"],
        factory=factory,
        proxies=[_BAD_PROXY_SENTINEL, None],
    )
    # Only slot1 built; slot0 was skipped due to InvalidProxyError.
    assert len(pool) == 1
    assert built_sessions == ["session-1"]


def test_ac3_bad_proxy_pool_does_not_crash() -> None:
    """AC3: a bad proxy raises InvalidProxyError logged+skipped — pool builds without crash."""
    _BAD_PROXY_SENTINEL = "__BAD2__"

    def factory(session: str, proxy: str | None = None) -> _ProxyCapturingClient:
        if proxy == _BAD_PROXY_SENTINEL:
            raise InvalidProxyError("invalid SOCKS5 proxy: no host")
        return _ProxyCapturingClient(proxy=proxy)

    # Must not raise — just build the remaining slot.
    pool = AccountPool.from_sessions(
        sessions=["bad", "good"],
        factory=factory,
        proxies=[_BAD_PROXY_SENTINEL, None],
    )
    assert pool.size == 1


def test_ac3_proxies_length_mismatch_raises_pool_config_error() -> None:
    """proxies list length != sessions length → PoolConfigError."""
    from collector.errors import PoolConfigError

    def factory(session: str, proxy: str | None = None) -> _ProxyCapturingClient:
        return _ProxyCapturingClient()

    with pytest.raises(PoolConfigError):
        AccountPool.from_sessions(
            sessions=["s0", "s1"],
            factory=factory,
            proxies=["socks5://h:1080"],  # length mismatch
        )


# ---------------------------------------------------------------------------
# FIX 1 — parse_socks5_proxy must raise InvalidProxyError on bad port
# ---------------------------------------------------------------------------


def test_parse_out_of_range_port_raises_invalid_proxy_error() -> None:
    """socks5://h:99999 → port out of range → InvalidProxyError (not ValueError)."""
    with pytest.raises(InvalidProxyError):
        parse_socks5_proxy("socks5://h:99999")


def test_parse_non_numeric_port_raises_invalid_proxy_error() -> None:
    """socks5://h:notaport → non-numeric port → InvalidProxyError (not ValueError)."""
    with pytest.raises(InvalidProxyError):
        parse_socks5_proxy("socks5://h:notaport")


def test_parse_bad_port_error_has_no_credentials() -> None:
    """Bad-port InvalidProxyError message must not include URI credentials.

    The URI carries username='secretuser' and password='p%40ss' (decoded: 'p@ss').
    Neither must appear in the error message.
    """
    with pytest.raises(InvalidProxyError) as exc_info:
        parse_socks5_proxy("socks5://secretuser:p%40ss@h:99999")
    msg = str(exc_info.value)
    assert "secretuser" not in msg
    assert "p%40ss" not in msg
    assert "p@ss" not in msg


def test_ac3_bad_port_proxy_skips_slot_and_pool_still_builds() -> None:
    """AC3 via real parse_socks5_proxy: a bad-PORT proxy raises InvalidProxyError
    inside the factory (via parse_socks5_proxy), the slot is skipped, and the pool
    still builds with the remaining good slot.

    This exercises the REAL parse_socks5_proxy → InvalidProxyError → from_sessions
    skip path (not a sentinel); FIX 1 is needed for this to pass.
    """

    def factory(session: str, proxy: str | None = None) -> _ProxyCapturingClient:
        # Mimic what build_telethon_client does: call parse_socks5_proxy when proxy
        # is not None, so the real parser is exercised and a bad-port URI raises.
        if proxy is not None:
            from collector.telegram.client import parse_socks5_proxy as real_parse

            proxy_tuple = real_parse(proxy)
            return _ProxyCapturingClient(proxy=str(proxy_tuple))
        return _ProxyCapturingClient(proxy=None)

    pool = AccountPool.from_sessions(
        sessions=["session-bad", "session-good"],
        factory=factory,
        proxies=["socks5://h:99999", None],  # bad port on slot 0
    )
    # slot 0 skipped (bad port → InvalidProxyError), slot 1 built fine.
    assert pool.size == 1


# ---------------------------------------------------------------------------
# FIX 3 — percent-decode proxy userinfo
# ---------------------------------------------------------------------------


def test_parse_percent_encoded_password() -> None:
    """socks5://u:p%40ss@h:1080 → password is decoded to 'p@ss'."""
    result = parse_socks5_proxy("socks5://u:p%40ss@h:1080")
    assert result[4] == "u"
    assert result[5] == "p@ss"


def test_parse_percent_encoded_username() -> None:
    """socks5://us%40er:pass@h:1080 → username is decoded to 'us@er'."""
    result = parse_socks5_proxy("socks5://us%40er:pass@h:1080")
    assert result[4] == "us@er"
    assert result[5] == "pass"


def test_parse_no_percent_encoding_unchanged() -> None:
    """Plain credentials without percent-encoding are returned as-is."""
    result = parse_socks5_proxy("socks5://user:pass@h:1080")
    assert result[4] == "user"
    assert result[5] == "pass"
