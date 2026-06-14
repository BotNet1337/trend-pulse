"""Unit tests for event categorization (T5) — RU + EN, most-specific wins."""

import pytest

from scorer.categorize import EventCategory, categorize


@pytest.mark.unit
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # LISTING
        ("Binance объявила листинг нового токена, торги открыты сегодня", EventCategory.LISTING),
        ("Coinbase will list the token; now trading on spot", EventCategory.LISTING),
        # HACK
        ("Протокол взломан, хакер похитил средства из пула", EventCategory.HACK),
        ("DeFi protocol exploited, funds drained in a breach", EventCategory.HACK),
        # REGULATION
        ("SEC подала иск, регулятор требует штраф", EventCategory.REGULATION),
        ("Regulator announces a ban; lawsuit filed against the exchange", EventCategory.REGULATION),
        # PRICE_MOVE
        ("Биткоин обновил максимум и вырос на 8% за сутки", EventCategory.PRICE_MOVE),
        ("ETH surge to a new all-time high, +12% today", EventCategory.PRICE_MOVE),
        # OTHER
        ("Доброе утро! Дайджест крипторынка за прошедшие сутки", EventCategory.OTHER),
        ("Weekly newsletter: thoughts on the ecosystem", EventCategory.OTHER),
    ],
)
def test_categorize(text: str, expected: EventCategory) -> None:
    assert categorize(text) is expected


@pytest.mark.unit
def test_precedence_hack_beats_price_move() -> None:
    # A hack that crashed the price is a HACK (more specific), not a PRICE_MOVE.
    assert categorize("Биржу взломали, токен рухнул на 40%") is EventCategory.HACK


@pytest.mark.unit
def test_precedence_regulation_beats_listing() -> None:
    assert categorize("SEC иск против биржи по листингу токена") is EventCategory.REGULATION


@pytest.mark.unit
def test_empty_is_other() -> None:
    assert categorize("") is EventCategory.OTHER
