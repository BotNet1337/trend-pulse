"""AC2 — validate_ref: public->True; private/bad/non-telegram->False; never raises."""

import pytest

from collector.base import SourceKind, SourceRef
from collector.telegram.reader import TelegramCollector

from .conftest import FakeClient, make_pool


@pytest.mark.asyncio
async def test_public_channel_validates_true() -> None:
    pool = make_pool([FakeClient(), FakeClient(), FakeClient()])
    collector = TelegramCollector(pool)

    assert await collector.validate_ref(SourceRef(SourceKind.TELEGRAM, "@public")) is True


@pytest.mark.asyncio
async def test_private_or_nonexistent_returns_false_without_raising() -> None:
    failing = [
        FakeClient(raise_on_entity=ValueError("No user has that username")),
        FakeClient(),
        FakeClient(),
    ]
    pool = make_pool(failing)
    collector = TelegramCollector(pool)

    # Must NOT raise outward — returns False.
    assert await collector.validate_ref(SourceRef(SourceKind.TELEGRAM, "@private")) is False


@pytest.mark.asyncio
async def test_non_telegram_kind_returns_false() -> None:
    pool = make_pool([FakeClient(), FakeClient(), FakeClient()])
    collector = TelegramCollector(pool)

    assert await collector.validate_ref(SourceRef(SourceKind.TWITTER, "@x")) is False
