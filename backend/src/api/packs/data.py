"""Curated channel pack catalog — static, immutable definitions (TASK-038).

The catalog is the single source of truth for pack slugs, titles, topics, and
the list of Telegram handles. Changes require a PR + review (no admin UI).

Handles curated 2026-06-10: every handle was verified live via the public
t.me/s/<handle> preview (real channel title + recent posts) — squatted or dead
handles (e.g. @wired, @startups) were rejected. Handles follow the format
validated by `TELEGRAM_HANDLE_PATTERN` (watchlist/schemas.py): '@' + 4-32 of
[A-Za-z0-9_]. Dead handles are silently skipped by the collector (ADR-001).

Two packs are required by TASK-038 as a baseline, a third added 2026-06-12:
  - crypto-ru  (~8 handles): Russian-language crypto / DeFi channels
  - tech-en    (~6 handles): English-language tech / startup channels
  - crypto-en  (~8 handles): English-language crypto / on-chain channels

Known limitation (by design, task doc §Discussion): subscribing a pack snapshot
the current handle list; if a pack is updated later, users must unsubscribe and
re-subscribe to get the new channels (no auto-sync, no migration).
"""

from dataclasses import dataclass

from storage.models.channels import SourceKind

# ─── Default alert config for pack-subscribed watchlist rows ─────────────────

# These are the defaults applied to EVERY watchlist row created by a pack
# subscribe. Users may update individual rows afterwards via PATCH /watchlists.
# Calibrated on the real-data eval (eval_offline/calibrate_threshold.py) for the v2
# 0-100 viral score: 50 is the best-F1 operating point (precision 0.72 / recall 0.66
# separating real ≥3-channel stories from single-channel noise). The old 70 was tuned
# for the pre-v2 unbounded score and on the v2 scale fires for almost nothing (recall
# ≈ 0.15). Users can raise it for higher-precision (fewer) alerts.
_DEFAULT_SCORE_THRESHOLD = 50
_DEFAULT_MIN_CHANNELS = 1
_DEFAULT_NOTIFICATION_LANG = "en"


@dataclass(frozen=True)
class PackChannel:
    """One channel entry in a pack — handle + source kind."""

    handle: str
    kind: SourceKind = SourceKind.TELEGRAM


@dataclass(frozen=True)
class PackDef:
    """Immutable definition of a curated pack."""

    slug: str
    title: str
    topic: str
    channels: tuple[PackChannel, ...]
    # Alert config defaults applied to each watchlist row on subscribe.
    default_score_threshold: int = _DEFAULT_SCORE_THRESHOLD
    default_min_channels: int = _DEFAULT_MIN_CHANNELS
    default_notification_lang: str = _DEFAULT_NOTIFICATION_LANG


# ─── Pack catalog ─────────────────────────────────────────────────────────────

# Each handle is a verified public Telegram @username (4-32 chars of
# [A-Za-z0-9_]); comments give the actual channel title + activity at curation.

_CRYPTO_RU_CHANNELS: tuple[PackChannel, ...] = (
    # Dense Russian-language crypto news set (29 handles, each re-verified live via
    # t.me/s 2026-06-13). DENSITY is the point: the viral score detects a story
    # spreading ACROSS channels, so the same crypto event must realistically land in
    # many of these at once. The old 8-handle pack left cross_channel ~0 in prod (only
    # 3 channels had data); this set was sourced from TGStat-adjacent directories +
    # vc.ru curated lists and gives real >=3-channel clusters (eval_offline/, 779 such
    # stories in a 9-month corpus). Subscriber counts (at verify) in comments.
    # -- core RU crypto news / media --
    PackChannel("@decenter"),  # DeCenter — 2.24M
    PackChannel("@investkingyru"),  # InvestKing — 2.1M
    PackChannel("@coin_post"),  # CoinPost — 300K
    PackChannel("@Pro_Blockchain"),  # Pro Blockchain — 176K
    PackChannel("@crypto_sekta"),  # Криптосекта — 167K
    PackChannel("@RBCCrypto"),  # РБК Крипто — 135K
    PackChannel("@crypto_hd"),  # Crypto Headlines — 135K
    PackChannel("@criptovest"),  # Криптовест — 130K
    PackChannel("@slezisatoshi"),  # Слёзы Сатоши — 128K
    PackChannel("@if_market_news"),  # InvestFuture Market News — 121K
    PackChannel("@incrypted"),  # Incrypted — 112K
    PackChannel("@icospeaksnews"),  # ICO Speaks News — 112K
    PackChannel("@binance_ru"),  # Binance Новости RU — 99.7K
    PackChannel("@forklog"),  # ForkLog — 94.1K
    PackChannel("@cryptodaily"),  # Crypto Daily — 89.7K
    PackChannel("@crypnews247"),  # CrypNews247 — 49.1K
    PackChannel("@blockchainrf"),  # Blockchain RF — 19.9K
    PackChannel("@bitcoin_cryptonews"),  # Bitcoin Crypto News — 17.8K
    PackChannel("@bitcoin_magazine"),  # Bitcoin Magazine RU — 15.2K
    PackChannel("@hashtelegraph"),  # Hash Telegraph — 13K
    PackChannel("@bitsmedia"),  # BITS.MEDIA — 10.5K
    PackChannel("@whattonews"),  # WhattoNews — 6.94K
    PackChannel("@web3news"),  # Web3 News RU — 5.98K
    # -- investing channels with heavy crypto coverage --
    PackChannel("@bitkogan"),  # Bitkogan — 263K
    PackChannel("@investfuture"),  # InvestFuture — 186K
    # -- TON ecosystem (dense co-clustering on TON news) --
    PackChannel("@toncoin_rus"),  # Toncoin RUS — 567K
    PackChannel("@tonworldru"),  # TON World RU — 410K
    PackChannel("@tonblockchain"),  # TON Blockchain — 199K
    PackChannel("@ruton"),  # RUTON — 139K
)

_TECH_EN_CHANNELS: tuple[PackChannel, ...] = (
    # English-language tech / startup / AI channels (verified 2026-06-10)
    PackChannel("@hacker_news_feed"),  # Hacker News — top HN stories, hourly
    PackChannel("@githubtrending"),  # GitHub Trends — trending repos, daily
    PackChannel("@durov"),  # Pavel Durov — founder updates, tech takes
    PackChannel("@telegram"),  # Telegram News — official platform news
    PackChannel("@futurism"),  # AI Post — AI news digest, daily
    PackChannel("@producthunt"),  # Venture Capital — startup/VC news, hourly
)

_CRYPTO_EN_CHANNELS: tuple[PackChannel, ...] = (
    # English-language crypto / on-chain / market channels (verified 2026-06-12
    # via t.me/s previews: live title + post within the last day, subs noted)
    PackChannel("@WatcherGuru"),  # Watcher Guru — breaking crypto/finance news, 628K
    PackChannel("@cointelegraph"),  # Cointelegraph — crypto news media, 366K
    PackChannel("@wublockchainenglish"),  # Wu Blockchain News — Asia/global crypto news, 291K
    PackChannel("@binance_announcements"),  # Binance Announcements — listings/official, 4M
    PackChannel("@CoinMarketCapAnnouncements"),  # CoinMarketCap Announcements, 259K
    PackChannel("@bitcoin"),  # Bitcoin — BTC community channel, 196K
    PackChannel("@unfolded"),  # unfolded. — charts/data-driven crypto, 121K
    PackChannel("@glassnode"),  # Glassnode — on-chain analytics, 44.5K
)

# The catalog is a frozen tuple — immutable at runtime (CONVENTIONS: no mutable globals).
PACK_CATALOG: tuple[PackDef, ...] = (
    PackDef(
        slug="crypto-ru",
        title="Crypto RU",
        topic="crypto",
        channels=_CRYPTO_RU_CHANNELS,
    ),
    PackDef(
        slug="tech-en",
        title="Tech EN",
        topic="tech",
        channels=_TECH_EN_CHANNELS,
    ),
    PackDef(
        slug="crypto-en",
        title="Crypto EN",
        topic="crypto",
        channels=_CRYPTO_EN_CHANNELS,
    ),
)

# ─── Lookup helpers ──────────────────────────────────────────────────────────

# Index by slug for O(1) lookup; built once at import time (frozen catalog).
_CATALOG_BY_SLUG: dict[str, PackDef] = {p.slug: p for p in PACK_CATALOG}


def get_pack(slug: str) -> PackDef | None:
    """Return the PackDef for *slug*, or None if not in the catalog."""
    return _CATALOG_BY_SLUG.get(slug)


def list_packs() -> tuple[PackDef, ...]:
    """Return the full catalog (immutable)."""
    return PACK_CATALOG


__all__ = [
    "PACK_CATALOG",
    "PackChannel",
    "PackDef",
    "get_pack",
    "list_packs",
]
