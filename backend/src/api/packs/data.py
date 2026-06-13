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
    # Russian-language crypto / DeFi / Web3 channels (verified 2026-06-10)
    PackChannel("@forklog"),  # ForkLog — крупнейшее RU крипто-медиа, посты ежедневно
    PackChannel("@incrypted"),  # Incrypted — крипто-новости и разборы, посты ежедневно
    PackChannel("@decenter"),  # DeCenter — блокчейн/биткоин/инвестиции, посты ежедневно
    PackChannel("@bitsmedia"),  # BITS.MEDIA — RU крипто-портал, посты ежедневно
    PackChannel("@binance_ru"),  # Binance Новости — официальный RU канал биржи
    PackChannel("@RBCCrypto"),  # РБК Крипто — крипто-редакция РБК, посты ежедневно
    PackChannel("@whattonews"),  # WhattoNews — новости TON-экосистемы
    PackChannel("@toncoin_rus"),  # Toncoin RUS — RU сообщество TON
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
