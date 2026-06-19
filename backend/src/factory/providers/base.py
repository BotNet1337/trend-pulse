"""The `SmsProvider` interface + DTO (TASK-133, testability).

The factory loop (TASK-134) depends ONLY on `SmsProvider` — never on httpx or
SMSPVA — so unit tests inject `FakeSmsProvider` (no network) while production wires
`SmsPvaProvider`. Money is `Decimal` (never float — budget-accounting precision).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class PurchasedNumber:
    """A number bought from an SMS provider: its opaque order id + the phone number.

    `order_id` is the provider's activation/order handle used to poll the code and to
    finish/cancel the order. `phone` is the rented number to register on Telegram.
    """

    order_id: str
    phone: str


@runtime_checkable
class SmsProvider(Protocol):
    """Minimal SMS-number surface the factory uses (buy → poll → finish/cancel).

    Non-OK upstream responses are mapped to typed `SmsProviderError` subclasses — the
    interface never returns sentinel error values or leaks the transport's exceptions.
    """

    async def balance(self) -> Decimal:
        """Return the account balance (provider currency) as a `Decimal`."""
        ...

    async def buy_number(self, *, country: str, service: str) -> PurchasedNumber:
        """Rent a number for `service` in `country`; raise on unavailability."""
        ...

    async def poll_code(self, order_id: str, *, timeout_seconds: int) -> str:
        """Poll until the SMS code for `order_id` arrives or the budget elapses."""
        ...

    async def finish(self, order_id: str) -> None:
        """Close `order_id` as successfully used (so it is not re-issued)."""
        ...

    async def cancel(self, order_id: str) -> None:
        """Release `order_id` unused (so the rental is not charged/held)."""
        ...

    async def aclose(self) -> None:
        """Release transport resources (best-effort)."""
        ...
