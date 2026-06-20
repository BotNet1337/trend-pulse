"""TASK-143 — SmsPvaRentProvider unit tests (httpx.MockTransport, no network).

The rental path (`/api/rent.php`, GET) leases long-lived REAL-SIM numbers (Telegram
service `opt29`) so Telegram accepts the registration — unlike the Activation numbers
(opt1) that were live-proven to be rejected. Asserts the create→activate→state-poll
buy flow, the SmsList code extraction (max `date`), best-effort cancel(=delete)/finish
(=no-op), balance via the activation `priemnik.php` endpoint, the `status:0` msg →
typed error mapping, and that the api_key NEVER appears in an error message.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest

from factory.constants import (
    RENT_BASE_PATH,
    RENT_DCOUNT_DEFAULT,
    RENT_DTYPE_DEFAULT,
    RENT_METOD_ACTIVATE,
    RENT_METOD_CREATE,
    RENT_METOD_DELETE,
    RENT_METOD_ORDERS,
    RENT_METOD_SMS,
    RENT_SVC_TELEGRAM,
    SMSPVA_BASE_URL,
    SMSPVA_DEFAULT_COUNTRY,
    SMSPVA_DEFAULT_SERVICE,
    SMSPVA_ENDPOINT_PATH,
    SMSPVA_METOD_BALANCE,
)
from factory.errors import (
    SmsCodeTimeoutError,
    SmsNumberUnavailableError,
    SmsProviderAuthError,
    SmsProviderResponseError,
)
from factory.providers.smspva_rent import SmsPvaRentProvider

_API_KEY = "secret-rent-key-xyz"

_Handler = Callable[[httpx.Request], httpx.Response]


def _provider_with(handler: _Handler) -> SmsPvaRentProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return SmsPvaRentProvider(
        api_key=_API_KEY,
        client=client,
        base_url=SMSPVA_BASE_URL,
        service=RENT_SVC_TELEGRAM,
        dtype=RENT_DTYPE_DEFAULT,
        dcount=RENT_DCOUNT_DEFAULT,
    )


def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr("factory.providers.smspva_rent.asyncio.sleep", fake_sleep)


async def test_buy_number_create_activate_then_poll_until_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_sleep(monkeypatch)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.params["method"]
        seen.append(method)
        assert request.url.path == RENT_BASE_PATH
        assert request.url.params["apikey"] == _API_KEY
        if method == RENT_METOD_CREATE:
            # create uses the configured rental service (opt29), NOT the arg slug (opt1).
            assert request.url.params["service"] == RENT_SVC_TELEGRAM
            assert request.url.params["country"] == SMSPVA_DEFAULT_COUNTRY
            assert request.url.params["dtype"] == RENT_DTYPE_DEFAULT
            assert request.url.params["dcount"] == str(RENT_DCOUNT_DEFAULT)
            return httpx.Response(
                200,
                json={
                    "status": 1,
                    "data": [
                        {
                            "id": 40370,
                            "pnumber": "9096037108",
                            "ccode": "+7",
                            "service": "opt29",
                            "until": 1587633960,
                        }
                    ],
                },
            )
        if method == RENT_METOD_ACTIVATE:
            assert request.url.params["id"] == "40370"
            return httpx.Response(200, json={"status": 1, "data": [{"id": 40370}]})
        if method == RENT_METOD_ORDERS:
            # First orders poll: still activating; second: active.
            already_active = seen.count(RENT_METOD_ORDERS) >= 2
            state = 1 if already_active else 2
            return httpx.Response(
                200,
                json={
                    "status": 1,
                    "data": [{"id": 40370, "state": state, "pnumber": "9096037108", "ccode": "+7"}],
                },
            )
        raise AssertionError(f"unexpected method {method}")

    provider = _provider_with(handler)
    number = await provider.buy_number(
        country=SMSPVA_DEFAULT_COUNTRY, service=SMSPVA_DEFAULT_SERVICE
    )
    assert number.order_id == "40370"
    assert number.phone == "+79096037108"
    assert seen[0] == RENT_METOD_CREATE
    assert seen[1] == RENT_METOD_ACTIVATE
    assert RENT_METOD_ORDERS in seen


async def test_buy_number_no_stock_maps_to_unavailable() -> None:
    provider = _provider_with(
        lambda req: httpx.Response(200, json={"status": 0, "msg": "No number available"})
    )
    with pytest.raises(SmsNumberUnavailableError):
        await provider.buy_number(country=SMSPVA_DEFAULT_COUNTRY, service=SMSPVA_DEFAULT_SERVICE)


async def test_buy_number_insufficient_balance_maps_to_response_error_without_key() -> None:
    provider = _provider_with(
        lambda req: httpx.Response(200, json={"status": 0, "msg": "Insufficient balance"})
    )
    with pytest.raises(SmsProviderResponseError) as exc:
        await provider.buy_number(country=SMSPVA_DEFAULT_COUNTRY, service=SMSPVA_DEFAULT_SERVICE)
    assert _API_KEY not in str(exc.value)


async def test_buy_number_bad_duration_maps_to_response_error() -> None:
    provider = _provider_with(
        lambda req: httpx.Response(
            200, json={"status": 0, "msg": "Incorrect duration count. Min 7 days. Max 90 days."}
        )
    )
    with pytest.raises(SmsProviderResponseError):
        await provider.buy_number(country=SMSPVA_DEFAULT_COUNTRY, service=SMSPVA_DEFAULT_SERVICE)


async def test_buy_number_activation_wait_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_sleep(monkeypatch)
    # Force the wait loop to be a single bounded attempt then give up.
    monkeypatch.setattr("factory.providers.smspva_rent.RENT_ACTIVATION_WAIT_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr("factory.providers.smspva_rent.RENT_ACTIVATION_POLL_INTERVAL_SECONDS", 5)

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.params["method"]
        if method == RENT_METOD_CREATE:
            return httpx.Response(
                200,
                json={"status": 1, "data": [{"id": 1, "pnumber": "9", "ccode": "+7"}]},
            )
        if method == RENT_METOD_ACTIVATE:
            return httpx.Response(200, json={"status": 1, "data": [{"id": 1}]})
        # orders: never active.
        return httpx.Response(200, json={"status": 1, "data": [{"id": 1, "state": 2}]})

    provider = _provider_with(handler)
    with pytest.raises(SmsCodeTimeoutError):
        await provider.buy_number(country=SMSPVA_DEFAULT_COUNTRY, service=SMSPVA_DEFAULT_SERVICE)


async def test_poll_code_extracts_telegram_code_from_smslist() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["method"] == RENT_METOD_SMS
        assert request.url.params["id"] == "40370"
        return httpx.Response(
            200,
            json={
                "status": 1,
                "data": {
                    "SmsList": [
                        {"text": "old Telegram code: 11111", "sender": "Telegram", "date": 100},
                        {"text": "Telegram code: 54321", "sender": "Telegram", "date": 200},
                    ],
                    "OtherSms": [],
                },
            },
        )

    provider = _provider_with(handler)
    # Picks the max-`date` entry (date=200) → code 54321.
    assert await provider.poll_code("40370", timeout_seconds=60) == "54321"


async def test_poll_code_skips_long_digit_run_and_extracts_real_code() -> None:
    # An SMS body that contains BOTH a long numeric run (a phone number) AND the real
    # 5-digit login code. The tightened regex must NOT partially match the long run — it
    # must extract the standalone 5-digit code.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": 1,
                "data": {
                    "SmsList": [
                        {
                            "text": "From +79091234567: Telegram code: 54321",
                            "sender": "Telegram",
                            "date": 1,
                        }
                    ],
                    "OtherSms": [],
                },
            },
        )

    provider = _provider_with(handler)
    assert await provider.poll_code("40370", timeout_seconds=60) == "54321"


async def test_poll_code_retries_until_sms_arrives(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_sleep(monkeypatch)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            # Empty SmsList = "not yet".
            return httpx.Response(200, json={"status": 1, "data": {"SmsList": [], "OtherSms": []}})
        return httpx.Response(
            200,
            json={"status": 1, "data": {"SmsList": [{"text": "code 778899", "date": 5}]}},
        )

    provider = _provider_with(handler)
    assert await provider.poll_code("40370", timeout_seconds=60) == "778899"
    assert calls["n"] == 2


async def test_poll_code_tolerates_missing_smslist(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_sleep(monkeypatch)
    # `data` present but no SmsList key, then a code arrives.
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(200, json={"status": 1, "data": {}})
        return httpx.Response(
            200, json={"status": 1, "data": {"SmsList": [{"text": "Your code: 44551", "date": 1}]}}
        )

    provider = _provider_with(handler)
    assert await provider.poll_code("40370", timeout_seconds=60) == "44551"


async def test_poll_code_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_sleep(monkeypatch)
    provider = _provider_with(
        lambda req: httpx.Response(200, json={"status": 1, "data": {"SmsList": []}})
    )
    with pytest.raises(SmsCodeTimeoutError):
        await provider.poll_code("40370", timeout_seconds=1)


async def test_cancel_uses_delete_method() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["method"] == RENT_METOD_DELETE
        assert request.url.params["id"] == "40370"
        return httpx.Response(200, json={"status": 1, "data": []})

    provider = _provider_with(handler)
    assert await provider.cancel("40370") is None


async def test_cancel_is_best_effort_on_failure() -> None:
    # A delete on an already-gone rental replies status:0 → cancel must NOT raise.
    provider = _provider_with(
        lambda req: httpx.Response(200, json={"status": 0, "msg": "Order not found"})
    )
    assert await provider.cancel("40370") is None


async def test_finish_is_noop_and_makes_no_request() -> None:
    # A rented number is KEPT alive (re-login during probation) — finish must NOT delete
    # it and must NOT raise.
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("finish() must not issue any request (rental kept alive)")

    provider = _provider_with(handler)
    assert await provider.finish("40370") is None


async def test_balance_uses_activation_priemnik_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Balance has no rent.php method → it hits the activation balance endpoint.
        assert request.url.path == SMSPVA_ENDPOINT_PATH
        assert request.url.params["metod"] == SMSPVA_METOD_BALANCE
        assert request.url.params["apikey"] == _API_KEY
        return httpx.Response(200, json={"response": "1", "balance": "412.50"})

    provider = _provider_with(handler)
    assert await provider.balance() == Decimal("412.50")


async def test_auth_error_maps_without_key() -> None:
    # An auth-style failure on create → typed auth error, no key leak.
    provider = _provider_with(
        lambda req: httpx.Response(200, json={"status": 0, "msg": "Invalid apikey"})
    )
    with pytest.raises(SmsProviderAuthError) as exc:
        await provider.buy_number(country=SMSPVA_DEFAULT_COUNTRY, service=SMSPVA_DEFAULT_SERVICE)
    assert _API_KEY not in str(exc.value)


async def test_http_500_maps_to_response_error_without_key() -> None:
    provider = _provider_with(lambda req: httpx.Response(500, json={}))
    with pytest.raises(SmsProviderResponseError) as exc:
        await provider.buy_number(country=SMSPVA_DEFAULT_COUNTRY, service=SMSPVA_DEFAULT_SERVICE)
    assert _API_KEY not in str(exc.value)


async def test_malformed_json_maps_to_response_error() -> None:
    provider = _provider_with(lambda req: httpx.Response(200, text="<html>nope</html>"))
    with pytest.raises(SmsProviderResponseError):
        await provider.buy_number(country=SMSPVA_DEFAULT_COUNTRY, service=SMSPVA_DEFAULT_SERVICE)


async def test_transport_error_does_not_leak_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    provider = _provider_with(handler)
    with pytest.raises(SmsProviderResponseError) as exc:
        await provider.buy_number(country=SMSPVA_DEFAULT_COUNTRY, service=SMSPVA_DEFAULT_SERVICE)
    assert _API_KEY not in str(exc.value)
    assert exc.value.__cause__ is None


async def test_aclose_closes_client() -> None:
    provider = _provider_with(lambda req: httpx.Response(200, json={}))
    assert await provider.aclose() is None
