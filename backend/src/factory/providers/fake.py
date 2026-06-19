"""Deterministic in-memory `SmsProvider` (TASK-133, CI-safe, no network).

Scenarios let TASK-134 test each branch deterministically:
  * `ok`      — buy returns a fixed number+order, poll returns a fixed code, finish/
                cancel are no-ops.
  * `no_code` — poll raises `SmsCodeTimeoutError` (the code-never-arrives branch).
  * `banned`  — buy raises `SmsNumberUnavailableError` (the no-number branch).

No sleeps, no I/O — every method resolves immediately and deterministically.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from factory.errors import SmsCodeTimeoutError, SmsNumberUnavailableError
from factory.providers.base import PurchasedNumber

# Deterministic fixtures (named — no magic literals in the impl).
FAKE_SMS_NUMBER: Final = "79990000000"
FAKE_SMS_ORDER_ID: Final = "fake-order-1"
FAKE_SMS_CODE: Final = "123456"
FAKE_DEFAULT_BALANCE: Final = Decimal("100.00")

_SCENARIO_OK: Final = "ok"
_SCENARIO_NO_CODE: Final = "no_code"
_SCENARIO_BANNED: Final = "banned"


class FakeSmsProvider:
    """A scripted `SmsProvider` for tests (structurally satisfies the Protocol)."""

    def __init__(
        self, *, scenario: str = _SCENARIO_OK, balance: Decimal = FAKE_DEFAULT_BALANCE
    ) -> None:
        self._scenario = scenario
        self._balance = balance

    async def balance(self) -> Decimal:
        return self._balance

    async def buy_number(self, *, country: str, service: str) -> PurchasedNumber:
        if self._scenario == _SCENARIO_BANNED:
            raise SmsNumberUnavailableError("fake: no number available (scenario=banned)")
        return PurchasedNumber(order_id=FAKE_SMS_ORDER_ID, phone=FAKE_SMS_NUMBER)

    async def poll_code(self, order_id: str, *, timeout_seconds: int) -> str:
        if self._scenario == _SCENARIO_NO_CODE:
            raise SmsCodeTimeoutError("fake: code never arrived (scenario=no_code)")
        return FAKE_SMS_CODE

    async def finish(self, order_id: str) -> None:
        return None

    async def cancel(self, order_id: str) -> None:
        return None

    async def aclose(self) -> None:
        """No-op — the fake holds no transport resources."""
        return None
