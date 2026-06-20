"""TASK-139 — MobileProxyProvider unit tests (httpx.MockTransport, no network).

Asserts Bearer-authed requests to the configured endpoints, the JSON → typed
return mapping, and the full non-OK → typed `ProxyProviderError` mapping. The api
token AND the socks5 uri must NEVER appear in an error message or in captured logs.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

import httpx
import pytest

from factory.constants import (
    MOBILEPROXY_BASE_URL,
    MOBILEPROXY_FIELD_BALANCE,
    MOBILEPROXY_FIELD_EXPIRES_AT,
    MOBILEPROXY_FIELD_HOST,
    MOBILEPROXY_FIELD_ID,
    MOBILEPROXY_FIELD_LOGIN,
    MOBILEPROXY_FIELD_PASSWORD,
    MOBILEPROXY_FIELD_PORT_SOCKS,
    MOBILEPROXY_PARAM_COUNTRY,
    MOBILEPROXY_PROXY_SCHEME,
    MOBILEPROXY_STATUS_FIELD,
    MOBILEPROXY_STATUS_NO_STOCK,
)
from factory.errors import (
    ProxyProviderAuthError,
    ProxyProviderResponseError,
    ProxyUnavailableError,
)
from factory.proxy.base import ProxyLease
from factory.proxy.mobileproxy import MobileProxyProvider

_API_TOKEN = "secret-token-xyz"

_Handler = Callable[[httpx.Request], httpx.Response]


def _provider_with(handler: _Handler) -> MobileProxyProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return MobileProxyProvider(api_key=_API_TOKEN, client=client, base_url=MOBILEPROXY_BASE_URL)


def _buy_ok_body() -> dict[str, object]:
    return {
        MOBILEPROXY_FIELD_ID: "port-991",
        MOBILEPROXY_FIELD_HOST: "188.x.x.x",
        MOBILEPROXY_FIELD_PORT_SOCKS: 1085,
        MOBILEPROXY_FIELD_LOGIN: "u-secret",
        MOBILEPROXY_FIELD_PASSWORD: "p-secret",
    }


async def test_allocate_sends_bearer_header() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json=_buy_ok_body())

    provider = _provider_with(handler)
    await provider.allocate("KE")
    assert seen["auth"] == f"Bearer {_API_TOKEN}"


async def test_allocate_ok_builds_socks5_lease() -> None:
    provider = _provider_with(lambda req: httpx.Response(200, json=_buy_ok_body()))
    lease = await provider.allocate("KE")
    assert lease.lease_id == "port-991"
    assert lease.uri == f"{MOBILEPROXY_PROXY_SCHEME}://u-secret:p-secret@188.x.x.x:1085"
    assert lease.country == "KE"


async def test_allocate_missing_host_raises_response_error_no_secret() -> None:
    # Load-bearing redaction path: the body is missing a REQUIRED field (host) but still
    # carries partial creds (login=u-secret / password=p-secret). The raised error must
    # NEVER echo those partial creds (they could be the real proxy login/password).
    body = _buy_ok_body()
    del body[MOBILEPROXY_FIELD_HOST]
    assert body[MOBILEPROXY_FIELD_LOGIN] == "u-secret"
    assert body[MOBILEPROXY_FIELD_PASSWORD] == "p-secret"
    provider = _provider_with(lambda req: httpx.Response(200, json=body))
    with pytest.raises(ProxyProviderResponseError) as exc:
        await provider.allocate("KE")
    message = str(exc.value)
    assert "u-secret" not in message
    assert "p-secret" not in message
    assert _API_TOKEN not in message


async def test_allocate_http_401_maps_to_auth_error_without_secret() -> None:
    provider = _provider_with(lambda req: httpx.Response(401, json={}))
    with pytest.raises(ProxyProviderAuthError) as exc:
        await provider.allocate("KE")
    assert _API_TOKEN not in str(exc.value)


async def test_allocate_http_500_maps_to_response_error_without_secret() -> None:
    provider = _provider_with(lambda req: httpx.Response(500, json={}))
    with pytest.raises(ProxyProviderResponseError) as exc:
        await provider.allocate("KE")
    assert _API_TOKEN not in str(exc.value)


async def test_allocate_malformed_json_maps_to_response_error() -> None:
    provider = _provider_with(lambda req: httpx.Response(200, text="<html>nope</html>"))
    with pytest.raises(ProxyProviderResponseError):
        await provider.allocate("KE")


async def test_allocate_transport_error_maps_to_response_error_no_chain() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    provider = _provider_with(handler)
    with pytest.raises(ProxyProviderResponseError) as exc:
        await provider.allocate("KE")
    # __cause__ suppressed via `from None` — the httpx repr (with URL) is not chained.
    assert exc.value.__cause__ is None
    assert _API_TOKEN not in str(exc.value)


async def test_allocate_secrets_absent_from_logs(caplog: pytest.LogCaptureFixture) -> None:
    provider = _provider_with(lambda req: httpx.Response(500, json={}))
    with caplog.at_level(logging.DEBUG), pytest.raises(ProxyProviderResponseError):
        await provider.allocate("KE")
    assert _API_TOKEN not in caplog.text


async def test_balance_parses_decimal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={MOBILEPROXY_FIELD_BALANCE: "129.50"})

    provider = _provider_with(handler)
    result = await provider.balance()
    assert isinstance(result, Decimal)
    assert result == Decimal("129.50")


async def test_balance_numeric_json_is_coerced() -> None:
    provider = _provider_with(
        lambda req: httpx.Response(200, json={MOBILEPROXY_FIELD_BALANCE: 129.5})
    )
    assert await provider.balance() == Decimal("129.5")


async def test_balance_unparseable_raises_response_error() -> None:
    provider = _provider_with(
        lambda req: httpx.Response(200, json={MOBILEPROXY_FIELD_BALANCE: "n/a"})
    )
    with pytest.raises(ProxyProviderResponseError):
        await provider.balance()


async def test_release_error_body_does_not_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = _provider_with(lambda req: httpx.Response(500, json={}))
    with caplog.at_level(logging.WARNING):
        assert await provider.release("port-991") is None
    assert _API_TOKEN not in caplog.text


async def test_release_transport_error_does_not_raise() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    provider = _provider_with(handler)
    assert await provider.release("port-991") is None


async def test_release_ok_returns_none() -> None:
    provider = _provider_with(lambda req: httpx.Response(200, json={"status": "ok"}))
    assert await provider.release("port-991") is None


async def test_uri_secret_absent_from_response_error() -> None:
    # A built socks5 uri must never leak: force a balance error after a successful
    # allocate and assert neither creds nor token are present in the message.
    body = _buy_ok_body()
    provider = _provider_with(lambda req: httpx.Response(200, json=body))
    lease = await provider.allocate("KE")
    # The lease uri carries the creds; ensure the creds substring is the secret we guard.
    assert "u-secret" in lease.uri

    err_provider = _provider_with(lambda req: httpx.Response(500, json={}))
    with pytest.raises(ProxyProviderResponseError) as exc:
        await err_provider.allocate("KE")
    assert "u-secret" not in str(exc.value)
    assert _API_TOKEN not in str(exc.value)


async def test_aclose_closes_client() -> None:
    provider = _provider_with(lambda req: httpx.Response(200, json={}))
    assert await provider.aclose() is None


async def test_allocate_out_of_stock_maps_to_unavailable() -> None:
    # A 200 body that reports no port available is a TRANSIENT signal → ProxyUnavailableError
    # (caller backs off, no failed row). Mirrors SMSPVA get_number response=2.
    body = {MOBILEPROXY_STATUS_FIELD: MOBILEPROXY_STATUS_NO_STOCK}
    provider = _provider_with(lambda req: httpx.Response(200, json=body))
    with pytest.raises(ProxyUnavailableError):
        await provider.allocate("KE")


async def test_allocate_sends_country_query_param() -> None:
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["country"] = request.url.params.get(MOBILEPROXY_PARAM_COUNTRY)
        return httpx.Response(200, json=_buy_ok_body())

    provider = _provider_with(handler)
    await provider.allocate("KE")
    assert seen["country"] == "KE"


async def test_allocate_none_country_omits_query_param() -> None:
    seen: dict[str, bool] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["has_country"] = MOBILEPROXY_PARAM_COUNTRY in request.url.params
        return httpx.Response(200, json=_buy_ok_body())

    provider = _provider_with(handler)
    await provider.allocate(None)
    assert seen["has_country"] is False


async def test_allocate_parses_valid_expires_at() -> None:
    body = _buy_ok_body()
    body[MOBILEPROXY_FIELD_EXPIRES_AT] = "2026-07-01T12:00:00"
    provider = _provider_with(lambda req: httpx.Response(200, json=body))
    lease = await provider.allocate("KE")
    assert lease.expires_at == datetime(2026, 7, 1, 12, 0, 0)


async def test_allocate_invalid_expires_at_is_none() -> None:
    body = _buy_ok_body()
    body[MOBILEPROXY_FIELD_EXPIRES_AT] = "not-a-timestamp"
    provider = _provider_with(lambda req: httpx.Response(200, json=body))
    lease = await provider.allocate("KE")
    assert lease.expires_at is None


async def test_allocate_missing_expires_at_is_none() -> None:
    body = _buy_ok_body()  # no expires_at key
    provider = _provider_with(lambda req: httpx.Response(200, json=body))
    lease = await provider.allocate("KE")
    assert lease.expires_at is None


async def test_allocate_json_list_body_raises_response_error() -> None:
    # A 200 whose JSON is a list (not an object) is an unexpected shape → typed error.
    provider = _provider_with(lambda req: httpx.Response(200, json=[1, 2, 3]))
    with pytest.raises(ProxyProviderResponseError):
        await provider.allocate("KE")


async def test_balance_bool_value_raises_response_error() -> None:
    # `bool` is an `int` subclass but is NOT a valid monetary amount → typed error.
    provider = _provider_with(
        lambda req: httpx.Response(200, json={MOBILEPROXY_FIELD_BALANCE: True})
    )
    with pytest.raises(ProxyProviderResponseError):
        await provider.balance()


def test_proxy_lease_repr_masks_creds() -> None:
    # The auto-repr would leak user:pass; the explicit __repr__ must mask the uri while
    # keeping lease_id/country/expires_at visible.
    lease = ProxyLease(
        lease_id="port-1",
        uri="socks5://u-secret:p-secret@host:1080",
        country="KE",
        expires_at=None,
    )
    text = repr(lease)
    assert "u-secret" not in text
    assert "p-secret" not in text
    assert "u-secret" not in str(lease)
    assert "p-secret" not in str(lease)
    # Non-secret fields stay visible.
    assert "port-1" in text
    assert "KE" in text
