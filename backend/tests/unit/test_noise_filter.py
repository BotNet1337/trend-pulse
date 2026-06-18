"""Unit tests for the ad/shill noise filter (T1 — anti-shill is the product moat).

Organic cross-channel news must pass; promo (sponsored) and coordinated (same text
seeded across channels at once) must be flagged so the scorer can exclude them.
DB-free pure compute — runs under ci-fast.
"""

import pytest

from scorer.noise_filter import (
    COORDINATED_WINDOW_SECONDS,
    ClusterPost,
    SignalKind,
    classify_cluster,
    is_noise,
    is_promotional,
)

_T0 = 1_700_000_000.0  # arbitrary epoch anchor


def _p(text: str, *, channel: int, dt: float = 0.0) -> ClusterPost:
    return ClusterPost(text=text, posted_at=_T0 + dt, channel_id=channel)


# ── is_promotional ───────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "text",
    [
        "🚀 Новый токен! Залетай, успей купить — промокод CRYPTO #реклама",
        "Sponsored: buy now at t.me/+abcdef gem 100x",
        "Партнёрский материал: airdrop, claim your tokens here utm_source=tg",
        "Аpe in 0x1234567890abcdef1234567890abcdef12345678 buy now",
        "referral link: ref=joinme, не финансовый совет",
    ],
)
def test_is_promotional_flags_ads(text: str) -> None:
    assert is_promotional(text) is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "text",
    [
        "Биткоин обновил локальный максимум на фоне данных по инфляции в США.",
        "SEC commissioner says some tokens may be excluded from securities status.",
        "ETH on track for a third consecutive red quarter, on-chain data shows.",
    ],
)
def test_is_promotional_passes_news(text: str) -> None:
    assert is_promotional(text) is False


# ── classify_cluster ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_organic_news_cluster_passes() -> None:
    # Same EVENT, DIFFERENT wording, spread over hours across distinct channels.
    posts = (
        _p("ФРС снизила ставку на 0.25%, Пауэлл сослался на рынок труда.", channel=1, dt=0),
        _p("Powell cuts rates by 25bps citing labor market softening.", channel=2, dt=1800),
        _p("Жёсткий разворот ФРС: ставка вниз на четверть пункта.", channel=3, dt=4200),
        _p("Fed delivers a 25bps cut; risk assets rally on the print.", channel=4, dt=6600),
    )
    assert classify_cluster(posts) is SignalKind.ORGANIC
    assert is_noise(posts) is False


@pytest.mark.unit
def test_promo_cluster_flagged() -> None:
    # Majority of posts carry ad markers → PROMO.
    posts = (
        _p("🚀 Новый GEM токен, залетай! промокод MOON #реклама", channel=1, dt=0),
        _p("Купи сейчас, 100x гарантирован, ref=shill t.me/+xyz", channel=1, dt=60),
        _p("Биткоин вырос на 2% за сутки.", channel=1, dt=120),  # one organic post
    )
    assert classify_cluster(posts) is SignalKind.PROMO
    assert is_noise(posts) is True


@pytest.mark.unit
def test_coordinated_seeding_flagged() -> None:
    # IDENTICAL text pushed across many channels within minutes → COORDINATED.
    seed = "Проект XYZ запускает стейкинг с доходностью 40 процентов годовых уже сегодня"
    posts = tuple(
        _p(seed, channel=ch, dt=ch * 30.0)  # all within ~2.5 min
        for ch in range(1, 6)
    )
    assert classify_cluster(posts) is SignalKind.COORDINATED
    assert is_noise(posts) is True


@pytest.mark.unit
def test_same_text_but_time_lagged_is_not_coordinated() -> None:
    # Identical wire text BUT propagated over many hours → organic syndication-spread,
    # not a simultaneous seeding burst (the time gate distinguishes them).
    seed = "Биржа Binance объявила о листинге нового актива на спотовом рынке сегодня днём"
    posts = tuple(
        _p(seed, channel=ch, dt=ch * (COORDINATED_WINDOW_SECONDS + 600.0))
        for ch in range(1, 6)
    )
    assert classify_cluster(posts) is not SignalKind.COORDINATED


@pytest.mark.unit
def test_single_channel_dup_is_not_coordinated() -> None:
    # Same text repeated on ONE channel is not cross-channel seeding.
    seed = "Утренний дайджест крипторынка и основные новости за прошедшие сутки сегодня"
    posts = tuple(_p(seed, channel=1, dt=i * 60.0) for i in range(5))
    assert classify_cluster(posts) is SignalKind.ORGANIC


@pytest.mark.unit
def test_empty_cluster_is_organic() -> None:
    assert classify_cluster(()) is SignalKind.ORGANIC
    assert is_noise(()) is False
