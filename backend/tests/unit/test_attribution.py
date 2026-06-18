"""Unit tests for source attribution (T4 — origin + spread timeline → lead-time)."""

import pytest

from scorer.attribution import AttributionPost, attribute

_T0 = 1_700_000_000.0


def _p(channel: int, dt: float) -> AttributionPost:
    return AttributionPost(channel_id=channel, posted_at=_T0 + dt)


@pytest.mark.unit
def test_origin_is_earliest_channel() -> None:
    # Channel 5 posts first, then it spreads to 2, 9, 3.
    tl = attribute([_p(5, 0), _p(2, 600), _p(9, 1800), _p(3, 4200)])
    assert tl is not None
    assert tl.origin_channel == 5
    assert tl.origin_at == _T0
    assert tl.channels_reached == 4


@pytest.mark.unit
def test_spread_order_and_lead_times() -> None:
    tl = attribute([_p(5, 0), _p(2, 600), _p(9, 1800), _p(3, 4200)])
    assert tl is not None
    assert [c for c, _ in tl.channel_first_seen] == [5, 2, 9, 3]
    assert tl.lead_time_seconds_to_nth_channel(1) == pytest.approx(0.0)
    assert tl.lead_time_seconds_to_nth_channel(2) == pytest.approx(600.0)
    assert tl.lead_time_seconds_to_nth_channel(4) == pytest.approx(4200.0)
    assert tl.lead_time_seconds_to_nth_channel(5) is None  # only 4 channels


@pytest.mark.unit
def test_first_seen_uses_earliest_post_per_channel() -> None:
    # A channel may post twice; first-seen is the EARLIER one.
    tl = attribute([_p(5, 0), _p(2, 600), _p(2, 100), _p(5, 5000)])
    assert tl is not None
    assert tl.origin_channel == 5
    # channel 2's first-seen is +100, so it is the 2nd channel at lead-time 100s.
    assert tl.lead_time_seconds_to_nth_channel(2) == pytest.approx(100.0)


@pytest.mark.unit
def test_channels_reached_by_window() -> None:
    tl = attribute([_p(5, 0), _p(2, 600), _p(9, 1800), _p(3, 4200)])
    assert tl is not None
    assert tl.channels_reached_by(0) == 1
    assert tl.channels_reached_by(600) == 2
    assert tl.channels_reached_by(2000) == 3
    assert tl.channels_reached_by(10_000) == 4


@pytest.mark.unit
def test_tie_breaks_by_channel_id() -> None:
    # Two channels post at the same instant → deterministic order by channel id.
    tl = attribute([_p(9, 0), _p(4, 0), _p(7, 0)])
    assert tl is not None
    assert tl.origin_channel == 4
    assert [c for c, _ in tl.channel_first_seen] == [4, 7, 9]


@pytest.mark.unit
def test_empty_returns_none() -> None:
    assert attribute([]) is None
