"""Unit tests for the actionable signal payload (T6) — composes T1-T5 into one object."""

import pytest

from scorer.categorize import EventCategory
from scorer.noise_filter import SignalKind
from scorer.score import ScoreInputs
from scorer.signal_payload import (
    CONFIRMATION_CHANNEL_N,
    SignalPost,
    build_signal_payload,
)

_T0 = 1_700_000_000.0


def _post(text: str, channel: int, dt: float) -> SignalPost:
    return SignalPost(text=text, channel_id=channel, posted_at=_T0 + dt)


def _base(**over: object) -> ScoreInputs:
    base: dict[str, object] = {
        "views": 8000,
        "forwards": 200,
        "reactions": 400,
        "channel_avg": 1.0,
        "delta_channel_count": 4,
        "delta_hours": 2.0,
        "unique_channels_count": 4,
        "watched_channels_count": 30,
    }
    base.update(over)
    return ScoreInputs(**base)  # type: ignore[arg-type]


@pytest.mark.unit
def test_organic_news_payload() -> None:
    posts = [
        _post("SEC подала иск против биржи, регулятор требует штраф", channel=5, dt=0),
        _post("Regulator files a lawsuit against the exchange", channel=2, dt=600),
        _post("Иск SEC: подробности судебного разбирательства", channel=9, dt=1800),
        _post("Lawsuit escalates as more details emerge", channel=3, dt=3600),
    ]
    p = build_signal_payload(posts=posts, base=_base(), independence_weights={})
    assert p is not None
    assert p.signal_kind is SignalKind.ORGANIC
    assert p.category is EventCategory.REGULATION
    assert p.origin_channel == 5
    assert p.total_channels == 4
    assert p.independent_channels == pytest.approx(4.0)  # no collusion → all independent
    assert p.headline_score > 0
    assert p.lead_time_to_confirmation_seconds == pytest.approx(1800.0)  # 3rd channel
    assert p.narrative.startswith("SEC подала иск")


@pytest.mark.unit
def test_promo_payload_scores_zero() -> None:
    posts = [
        _post("🚀 Новый GEM! Залетай, промокод MOON #реклама", channel=1, dt=0),
        _post("Купи сейчас, 100x, ref=shill t.me/+xyz", channel=1, dt=60),
    ]
    p = build_signal_payload(posts=posts, base=_base(), independence_weights={})
    assert p is not None
    assert p.signal_kind is SignalKind.PROMO
    assert p.headline_score == 0.0


@pytest.mark.unit
def test_shill_ring_collapses_independent_reach() -> None:
    # Five channels carry the SAME event but with VARIED wording (so it is ORGANIC, not
    # coordinated seeding) — yet the channels are a known colluding ring (weights 0.2).
    # Effective independent reach ≈ 1, so the ring scores far below 5 independents.
    texts = [
        "Биткоин вырос на 9% и обновил максимум на фоне притока в ETF",
        "BTC hits a fresh all-time high as ETF inflows accelerate",
        "Новый максимум биткоина: рынок отреагировал ростом альткоинов",
        "Bitcoin surges past its previous peak, +9% on the day",
        "Биткоин на пике цикла — аналитики обсуждают цели",
    ]
    posts = [_post(texts[c - 1], channel=c, dt=c * 60.0) for c in range(1, 6)]
    ring = {c: 0.2 for c in range(1, 6)}  # one 5-channel ring
    base5 = _base(unique_channels_count=5)

    p = build_signal_payload(posts=posts, base=base5, independence_weights=ring)
    assert p is not None
    assert p.signal_kind is SignalKind.ORGANIC
    assert p.independent_channels == pytest.approx(1.0)
    assert p.category is EventCategory.PRICE_MOVE

    indep = build_signal_payload(posts=posts, base=base5, independence_weights={})
    assert indep is not None
    assert indep.headline_score > p.headline_score  # 5 independents > 5-channel ring


@pytest.mark.unit
def test_lead_time_none_when_below_confirmation() -> None:
    # Fewer than CONFIRMATION_CHANNEL_N channels → no confirmation lead-time.
    assert CONFIRMATION_CHANNEL_N == 3
    posts = [_post("a single-channel story here, long enough text", channel=1, dt=0)]
    p = build_signal_payload(
        posts=posts, base=_base(unique_channels_count=1), independence_weights={}
    )
    assert p is not None
    assert p.lead_time_to_confirmation_seconds is None


@pytest.mark.unit
def test_empty_returns_none() -> None:
    assert build_signal_payload(posts=[], base=_base(), independence_weights={}) is None
