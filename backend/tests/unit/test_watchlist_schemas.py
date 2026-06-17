"""Unit tests for watchlist boundary schemas (no DB)."""

import pytest
from pydantic import ValidationError

from api.watchlist.schemas import (
    AlertConfig,
    ChannelRef,
    WatchlistCreate,
    WatchlistSignal,
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


# --- Twitter source handle validation (TASK-031, per-source) -----------------


@pytest.mark.parametrize("handle", ["VitalikButerin", "@cobie", "lopp", "a", "x" * 15])
def test_channel_ref_accepts_valid_twitter_handle(handle: str) -> None:
    ref = ChannelRef(handle=handle, kind=SourceKind.TWITTER)
    assert ref.kind is SourceKind.TWITTER
    assert ref.handle == handle


@pytest.mark.parametrize(
    "handle",
    ["bad handle!", "@bad-dash", "x" * 16, "@" + "y" * 16, "with.dot", ""],
)
def test_channel_ref_rejects_bad_twitter_handle(handle: str) -> None:
    with pytest.raises(ValidationError):
        ChannelRef(handle=handle, kind=SourceKind.TWITTER)


def test_telegram_handle_rejected_as_twitter_when_too_long() -> None:
    # A 20-char handle is a valid-ish Telegram name but too long for Twitter (≤15).
    ChannelRef(handle="@" + "a" * 20, kind=SourceKind.TELEGRAM)  # ok for telegram
    with pytest.raises(ValidationError):
        ChannelRef(handle="a" * 20, kind=SourceKind.TWITTER)


# --- Reddit source handle validation (TASK-092, per-source) ------------------


@pytest.mark.parametrize("handle", ["CryptoCurrency", "r/Bitcoin", "ethtrader", "abc", "x" * 21])
def test_channel_ref_accepts_valid_reddit_handle(handle: str) -> None:
    ref = ChannelRef(handle=handle, kind=SourceKind.REDDIT)
    assert ref.kind is SourceKind.REDDIT
    assert ref.handle == handle


@pytest.mark.parametrize(
    "handle",
    ["bad sub!", "ab", "x" * 22, "with.dot", "@cobie", "r/ab", ""],
)
def test_channel_ref_rejects_bad_reddit_handle(handle: str) -> None:
    with pytest.raises(ValidationError):
        ChannelRef(handle=handle, kind=SourceKind.REDDIT)


def test_twitter_handle_rejected_as_reddit_when_too_short() -> None:
    # A 1-char handle is fine for Twitter but too short for a subreddit (≥3).
    ChannelRef(handle="a", kind=SourceKind.TWITTER)  # ok for twitter
    with pytest.raises(ValidationError):
        ChannelRef(handle="a", kind=SourceKind.REDDIT)


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


# --- WatchlistSignal.effective_sources (TASK-126) ---------------------------------


def test_watchlist_signal_effective_sources_defaults_to_none() -> None:
    """The independence field is nullable and absent by default (graceful)."""
    signal = WatchlistSignal()
    assert signal.effective_sources is None


def test_watchlist_signal_serializes_effective_sources_value() -> None:
    """A real float is carried through serialization unchanged."""
    signal = WatchlistSignal(live_score=55.0, effective_sources=3.0)
    dumped = signal.model_dump()
    assert dumped["effective_sources"] == pytest.approx(3.0)


def test_watchlist_signal_serializes_effective_sources_null() -> None:
    """`None` serializes as null (never fabricated — INV2)."""
    assert WatchlistSignal().model_dump()["effective_sources"] is None


def test_watchlist_signal_forbids_extra_fields() -> None:
    """`extra='forbid'` is preserved (no silent unknown fields)."""
    with pytest.raises(ValidationError):
        WatchlistSignal.model_validate({"unknown_field": 1})
