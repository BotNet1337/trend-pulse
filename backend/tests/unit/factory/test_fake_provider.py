"""TASK-133 — FakeSmsProvider unit tests (deterministic, no network).

`ok` → buy returns a deterministic number+order, poll returns a deterministic
code, finish/cancel no-op. `no_code` → poll raises SmsCodeTimeoutError. `banned`
→ buy raises SmsNumberUnavailableError (the failure branch TASK-134 exercises).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from factory.constants import SMSPVA_DEFAULT_COUNTRY, SMSPVA_DEFAULT_SERVICE
from factory.errors import SmsCodeTimeoutError, SmsNumberUnavailableError
from factory.providers.base import PurchasedNumber, SmsProvider
from factory.providers.fake import (
    FAKE_SMS_CODE,
    FAKE_SMS_NUMBER,
    FAKE_SMS_ORDER_ID,
    FakeSmsProvider,
)


def test_fake_provider_satisfies_protocol() -> None:
    assert isinstance(FakeSmsProvider(), SmsProvider)


async def test_fake_balance_is_deterministic() -> None:
    provider = FakeSmsProvider(balance=Decimal("42.50"))
    assert await provider.balance() == Decimal("42.50")


async def test_fake_ok_buy_returns_deterministic_number() -> None:
    provider = FakeSmsProvider(scenario="ok")
    number = await provider.buy_number(
        country=SMSPVA_DEFAULT_COUNTRY, service=SMSPVA_DEFAULT_SERVICE
    )
    assert number == PurchasedNumber(order_id=FAKE_SMS_ORDER_ID, phone=FAKE_SMS_NUMBER)


async def test_fake_ok_poll_returns_deterministic_code() -> None:
    provider = FakeSmsProvider(scenario="ok")
    code = await provider.poll_code(FAKE_SMS_ORDER_ID, timeout_seconds=1)
    assert code == FAKE_SMS_CODE


async def test_fake_ok_finish_and_cancel_are_noop() -> None:
    provider = FakeSmsProvider(scenario="ok")
    assert await provider.finish(FAKE_SMS_ORDER_ID) is None
    assert await provider.cancel(FAKE_SMS_ORDER_ID) is None


async def test_fake_no_code_poll_raises_timeout() -> None:
    provider = FakeSmsProvider(scenario="no_code")
    with pytest.raises(SmsCodeTimeoutError):
        await provider.poll_code(FAKE_SMS_ORDER_ID, timeout_seconds=1)


async def test_fake_banned_buy_raises_unavailable() -> None:
    provider = FakeSmsProvider(scenario="banned")
    with pytest.raises(SmsNumberUnavailableError):
        await provider.buy_number(country=SMSPVA_DEFAULT_COUNTRY, service=SMSPVA_DEFAULT_SERVICE)


async def test_fake_aclose_is_noop() -> None:
    provider = FakeSmsProvider()
    assert await provider.aclose() is None
