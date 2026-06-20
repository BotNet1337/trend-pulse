"""TASK-134 fix — `_provision` must RELEASE a bought number when registration fails.

Live evidence: Telegram rejects SMS-service numbers (PhoneNumberInvalid/Banned) — the
COMMON case. Without a `cancel`, every failed registration leaks the paid number's cost.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from factory.errors import RegistrarBannedError
from factory.providers.base import PurchasedNumber
from factory.tasks import _provision


class _RecordingProvider:
    """A minimal SmsProvider that records finish/cancel so the test can assert release."""

    def __init__(self) -> None:
        self.cancelled: list[str] = []
        self.finished: list[str] = []

    async def balance(self) -> Decimal:
        return Decimal("10.00")

    async def buy_number(self, *, country: str, service: str) -> PurchasedNumber:
        return PurchasedNumber(order_id="o1", phone="+70000000000")

    async def poll_code(self, order_id: str, *, timeout_seconds: int) -> str:
        return "123456"

    async def finish(self, order_id: str) -> None:
        self.finished.append(order_id)

    async def cancel(self, order_id: str) -> None:
        self.cancelled.append(order_id)

    async def aclose(self) -> None:
        return None


class _FailingRegistrar:
    """A registrar that consumes the code then fails — as Telegram does for SMS numbers."""

    async def register(self, *, phone: str, code_cb, proxy: str | None = None):  # type: ignore[no-untyped-def]
        await code_cb()
        raise RegistrarBannedError("telegram banned this phone number")


async def test_provision_releases_number_when_registration_fails() -> None:
    provider = _RecordingProvider()
    with pytest.raises(RegistrarBannedError):
        await _provision(
            provider, _FailingRegistrar(), proxy_provider=None, country="RU", static_proxy=None
        )
    # The bought number was RELEASED (refund), not leaked; finish was NOT called.
    assert provider.cancelled == ["o1"]
    assert provider.finished == []


class _OkRegistrar:
    async def register(self, *, phone: str, code_cb, proxy: str | None = None):  # type: ignore[no-untyped-def]
        from factory.registrar.base import RegisteredSession

        await code_cb()
        return RegisteredSession(session_string="1Aok", tg_user_id=42)


async def test_provision_finishes_number_on_success() -> None:
    provider = _RecordingProvider()
    purchased, registered, lease = await _provision(
        provider, _OkRegistrar(), proxy_provider=None, country="RU", static_proxy=None
    )
    assert lease is None
    assert purchased.order_id == "o1"
    assert registered.tg_user_id == 42
    assert provider.finished == ["o1"]  # order closed as used
    assert provider.cancelled == []  # no release on success
