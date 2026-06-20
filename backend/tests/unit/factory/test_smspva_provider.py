"""TASK-133 — SmsPvaProvider unit tests (httpx.MockTransport, no network).

Asserts authed GET requests (metod/service/apikey/country/id params), JSON parse
into typed return values, and the full non-OK → typed domain error mapping. The
api_key must NEVER appear in an error message.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest

from factory.constants import (
    SMSPVA_BASE_URL,
    SMSPVA_DEFAULT_COUNTRY,
    SMSPVA_DEFAULT_SERVICE,
    SMSPVA_ENDPOINT_PATH,
    SMSPVA_METOD_BALANCE,
    SMSPVA_METOD_BAN,
    SMSPVA_METOD_DENIAL,
    SMSPVA_METOD_NUMBER,
    SMSPVA_METOD_SMS,
)
from factory.errors import (
    SmsCodeTimeoutError,
    SmsNumberUnavailableError,
    SmsProviderAuthError,
    SmsProviderResponseError,
)
from factory.providers.smspva import SmsPvaProvider

_API_KEY = "secret-key-xyz"

_Handler = Callable[[httpx.Request], httpx.Response]


def _provider_with(handler: _Handler) -> SmsPvaProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return SmsPvaProvider(api_key=_API_KEY, client=client, base_url=SMSPVA_BASE_URL)


async def test_balance_builds_authed_request_and_parses_decimal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == SMSPVA_ENDPOINT_PATH
        assert request.url.params["metod"] == SMSPVA_METOD_BALANCE
        assert request.url.params["apikey"] == _API_KEY
        return httpx.Response(200, json={"response": "1", "balance": "385.00"})

    provider = _provider_with(handler)
    assert await provider.balance() == Decimal("385.00")


async def test_buy_number_parses_number_and_order_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["metod"] == SMSPVA_METOD_NUMBER
        assert request.url.params["country"] == SMSPVA_DEFAULT_COUNTRY
        assert request.url.params["service"] == SMSPVA_DEFAULT_SERVICE
        return httpx.Response(200, json={"response": "1", "number": "9871234567", "id": "25623"})

    provider = _provider_with(handler)
    number = await provider.buy_number(
        country=SMSPVA_DEFAULT_COUNTRY, service=SMSPVA_DEFAULT_SERVICE
    )
    assert number.order_id == "25623"
    assert number.phone == "9871234567"


async def test_buy_number_coerces_integer_number_and_id() -> None:
    # SMSPVA returns `number`/`id` as JSON INTEGERS for some countries (observed live:
    # ID/PH). They are valid identifiers → the provider must coerce, not raise
    # "unexpected shape" (which would make the factory skip a country that has stock).
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "1", "number": 84931234567, "id": 25623})

    provider = _provider_with(handler)
    number = await provider.buy_number(
        country=SMSPVA_DEFAULT_COUNTRY, service=SMSPVA_DEFAULT_SERVICE
    )
    assert number.order_id == "25623"
    assert number.phone == "84931234567"


async def test_buy_number_unavailable_raises_typed_error() -> None:
    provider = _provider_with(lambda req: httpx.Response(200, json={"response": "2"}))
    with pytest.raises(SmsNumberUnavailableError):
        await provider.buy_number(country=SMSPVA_DEFAULT_COUNTRY, service=SMSPVA_DEFAULT_SERVICE)


async def test_poll_code_returns_sms_when_ready() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["metod"] == SMSPVA_METOD_SMS
        assert request.url.params["id"] == "25623"
        return httpx.Response(200, json={"response": "1", "number": "987", "sms": "234562"})

    provider = _provider_with(handler)
    assert await provider.poll_code("25623", timeout_seconds=60) == "234562"


async def test_poll_code_retries_until_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(200, json={"response": "2", "sms": None})
        return httpx.Response(200, json={"response": "1", "sms": "111222"})

    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("factory.providers.smspva.asyncio.sleep", fake_sleep)
    provider = _provider_with(handler)
    assert await provider.poll_code("25623", timeout_seconds=60) == "111222"
    assert calls["n"] == 2
    assert len(slept) == 1


async def test_poll_code_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr("factory.providers.smspva.asyncio.sleep", fake_sleep)
    provider = _provider_with(lambda req: httpx.Response(200, json={"response": "2", "sms": None}))
    with pytest.raises(SmsCodeTimeoutError):
        # Budget shorter than interval → at most one attempt then timeout.
        await provider.poll_code("25623", timeout_seconds=1)


async def test_finish_uses_ban_metod_and_accepts_responce_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["metod"] == SMSPVA_METOD_BAN
        return httpx.Response(200, json={"responce": "1", "id": "25623"})

    provider = _provider_with(handler)
    assert await provider.finish("25623") is None


async def test_finish_is_best_effort_on_non_ok_response() -> None:
    # Cleanup verbs must NOT raise — a consumed/expired order replies non-OK (live: 3
    # "Invalid params"); the request still releases it server-side. Raising here would
    # mask the surrounding flow's real outcome.
    provider = _provider_with(lambda req: httpx.Response(200, json={"response": "3"}))
    assert await provider.finish("25623") is None


async def test_cancel_uses_denial_metod() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["metod"] == SMSPVA_METOD_DENIAL
        return httpx.Response(200, json={"responce": "1", "id": "25623"})

    provider = _provider_with(handler)
    assert await provider.cancel("25623") is None


async def test_cancel_is_best_effort_on_non_ok_response() -> None:
    # cancel() releases a number whose registration failed → must never raise even when
    # the order is already gone (response=3) or the transport hiccups.
    provider = _provider_with(lambda req: httpx.Response(200, json={"response": "3"}))
    assert await provider.cancel("25623") is None


async def test_auth_error_maps_to_auth_error_without_key() -> None:
    provider = _provider_with(
        lambda req: httpx.Response(200, json={"response": "error", "error_msg": "bad key"})
    )
    with pytest.raises(SmsProviderAuthError) as exc:
        await provider.balance()
    assert _API_KEY not in str(exc.value)


async def test_rate_limit_code_maps_to_response_error() -> None:
    provider = _provider_with(lambda req: httpx.Response(200, json={"response": "5"}))
    with pytest.raises(SmsProviderResponseError):
        await provider.balance()


async def test_http_500_maps_to_response_error_without_key() -> None:
    provider = _provider_with(lambda req: httpx.Response(500, json={}))
    with pytest.raises(SmsProviderResponseError) as exc:
        await provider.balance()
    assert _API_KEY not in str(exc.value)


async def test_malformed_json_maps_to_response_error() -> None:
    provider = _provider_with(lambda req: httpx.Response(200, text="<html>nope</html>"))
    with pytest.raises(SmsProviderResponseError):
        await provider.balance()


async def test_aclose_closes_client() -> None:
    provider = _provider_with(lambda req: httpx.Response(200, json={}))
    # Should not raise; closes the underlying MockTransport client.
    assert await provider.aclose() is None
