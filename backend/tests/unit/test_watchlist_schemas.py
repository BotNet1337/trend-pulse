"""Unit tests for watchlist boundary schemas (no DB)."""

import pytest
from pydantic import ValidationError

from api.watchlist.schemas import (
    AlertConfig,
    ChannelRef,
    WatchlistCreate,
)
from storage.models.channels import SourceKind


def test_channel_ref_accepts_valid_handle() -> None:
    ref = ChannelRef(handle="@good_handle")
    assert ref.handle == "@good_handle"


def test_channel_ref_defaults_kind_to_telegram() -> None:
    assert ChannelRef(handle="@some_chan").kind is SourceKind.TELEGRAM


def test_channel_ref_explicit_telegram_equivalent() -> None:
    assert ChannelRef(handle="@some_chan", kind=SourceKind.TELEGRAM).kind is SourceKind.TELEGRAM


@pytest.mark.parametrize(
    "handle",
    ["bad handle!", "@bad handle!", "@ab", "no_at_prefix", "@" + "x" * 33, "@bad-dash"],
)
def test_channel_ref_rejects_bad_handle(handle: str) -> None:
    with pytest.raises(ValidationError):
        ChannelRef(handle=handle)


@pytest.mark.parametrize("threshold", [-1, 101, 1000])
def test_alert_config_rejects_out_of_range_threshold(threshold: int) -> None:
    with pytest.raises(ValidationError):
        AlertConfig(score_threshold=threshold, min_channels=1, notification_lang="en")


def test_alert_config_rejects_min_channels_below_one() -> None:
    with pytest.raises(ValidationError):
        AlertConfig(score_threshold=50, min_channels=0, notification_lang="en")


@pytest.mark.parametrize("lang", ["EN", "eng", "e", "1n", "русск"])
def test_alert_config_rejects_non_iso_lang(lang: str) -> None:
    with pytest.raises(ValidationError):
        AlertConfig(score_threshold=50, min_channels=1, notification_lang=lang)


def test_alert_config_default_lang_is_en() -> None:
    cfg = AlertConfig(score_threshold=50, min_channels=1)
    assert cfg.notification_lang == "en"


def test_watchlist_create_rejects_empty_topic() -> None:
    with pytest.raises(ValidationError):
        WatchlistCreate(
            topic="",
            channel=ChannelRef(handle="@chan_name"),
            alert_config=AlertConfig(score_threshold=50, min_channels=1),
        )


def test_watchlist_create_valid() -> None:
    model = WatchlistCreate(
        topic="ai",
        channel=ChannelRef(handle="@chan_name"),
        alert_config=AlertConfig(score_threshold=50, min_channels=2),
    )
    assert model.topic == "ai"
    assert model.channel.kind is SourceKind.TELEGRAM
