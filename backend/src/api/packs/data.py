"""Curated channel pack catalog — static, immutable definitions (TASK-038).

The catalog is the single source of truth for pack slugs, titles, topics, and
the list of Telegram handles. Changes require a PR + review (no admin UI).

Handles curated 2026-06-10: every handle was verified live via the public
t.me/s/<handle> preview (real channel title + recent posts) — squatted or dead
handles (e.g. @wired, @startups) were rejected. Handles follow the format
validated by `TELEGRAM_HANDLE_PATTERN` (watchlist/schemas.py): '@' + 4-32 of
[A-Za-z0-9_]. Dead handles are silently skipped by the collector (ADR-001).

Two packs are required by TASK-038 as a baseline, a third added 2026-06-12, a
fourth (Twitter/X) added 2026-06-14 (TASK-031/089), a fifth (Reddit) added
2026-06-14 (TASK-092/093), a sixth (event-overlap crypto-RU) added 2026-06-17
(TASK-128):
  - crypto-ru         (~29 handles): Russian-language crypto / DeFi Telegram channels
  - tech-en           (~6 handles):  English-language tech / startup Telegram channels
  - crypto-en         (~8 handles):  English-language crypto / on-chain Telegram channels
  - crypto-twitter    (~40 handles): crypto Twitter/X accounts (RU+EN), kind=TWITTER
  - crypto-reddit     (~22 subs):    crypto subreddits (mostly EN), kind=REDDIT
  - crypto-ru-overlap (~20 handles): event-overlap crypto-RU TG (aggregators + origins)

The Twitter pack handles are CANDIDATES (well-known accounts); live existence is
not pre-validated here because it requires TWITTER_BEARER_TOKEN (owner-gated). Dead
or renamed handles are silently skipped by the collector at read time (resolve →
None → skip), exactly like dead Telegram handles. When the key is configured a
follow-up run prunes the dead ones via TwitterCollector.validate_ref (TASK-089).
Handles are stored bare + lowercased (the collector's canonical form) and are ≤15
chars (X username limit).

The Reddit pack subreddits are likewise CANDIDATES; live existence is owner-gated on
REDDIT_CLIENT_ID/SECRET/USER_AGENT and pruned via RedditCollector.validate_ref
(TASK-093). Subreddit handles are stored bare + lowercased without the `r/` prefix
(the collector's canonical form) and are 3-21 chars of [a-z0-9_] (subreddit-name
rules — no hyphens). RU-only crypto subreddits are scarce (most RU audience is on
Telegram); dead/private subs are silently skipped at read time.

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
# 0-100 viral score. LIVE-recalibrated to 32: offline best-F1 was 50, but the live
# scorer scores FRESH clusters before views/engagement mature, so live viral_score
# tops out ~44 — at 50 almost nothing fires. 32 sits just below the v2 multi-channel
# band so genuine cross-channel stories alert; users can raise it for fewer alerts.
_DEFAULT_SCORE_THRESHOLD = 32
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

_CRYPTO_TWITTER_CHANNELS: tuple[PackChannel, ...] = (
    # Crypto Twitter/X accounts (TASK-031/089), bare + lowercase usernames (≤15 chars).
    # CANDIDATES — live existence pruned later via validate_ref once TWITTER_BEARER_TOKEN
    # is set (owner-gated); dead/renamed handles are skipped by the collector at read time.
    # -- EN: founders / analysts / on-chain / media --
    PackChannel("vitalikbuterin", kind=SourceKind.TWITTER),
    PackChannel("balajis", kind=SourceKind.TWITTER),
    PackChannel("saylor", kind=SourceKind.TWITTER),
    PackChannel("apompliano", kind=SourceKind.TWITTER),
    PackChannel("cryptohayes", kind=SourceKind.TWITTER),
    PackChannel("cobie", kind=SourceKind.TWITTER),
    PackChannel("pentosh1", kind=SourceKind.TWITTER),
    PackChannel("woonomic", kind=SourceKind.TWITTER),
    PackChannel("wclementeiii", kind=SourceKind.TWITTER),
    PackChannel("100trillionusd", kind=SourceKind.TWITTER),
    PackChannel("rektcapital", kind=SourceKind.TWITTER),
    PackChannel("cryptokaleo", kind=SourceKind.TWITTER),
    PackChannel("intocryptoverse", kind=SourceKind.TWITTER),
    PackChannel("ryansadams", kind=SourceKind.TWITTER),
    PackChannel("trustlessstate", kind=SourceKind.TWITTER),
    PackChannel("cburniske", kind=SourceKind.TWITTER),
    PackChannel("haydenzadams", kind=SourceKind.TWITTER),
    PackChannel("stanikulechov", kind=SourceKind.TWITTER),
    PackChannel("erikvoorhees", kind=SourceKind.TWITTER),
    PackChannel("lopp", kind=SourceKind.TWITTER),
    PackChannel("gavofyork", kind=SourceKind.TWITTER),
    PackChannel("messaricrypto", kind=SourceKind.TWITTER),
    PackChannel("glassnode", kind=SourceKind.TWITTER),
    PackChannel("santimentfeed", kind=SourceKind.TWITTER),
    PackChannel("defillama", kind=SourceKind.TWITTER),
    PackChannel("lookonchain", kind=SourceKind.TWITTER),
    PackChannel("whalealert", kind=SourceKind.TWITTER),
    PackChannel("watcherguru", kind=SourceKind.TWITTER),
    PackChannel("cointelegraph", kind=SourceKind.TWITTER),
    PackChannel("coindesk", kind=SourceKind.TWITTER),
    PackChannel("theblock__", kind=SourceKind.TWITTER),
    # -- RU: Russian-language crypto media / analysts --
    PackChannel("forklog", kind=SourceKind.TWITTER),
    PackChannel("rbc_crypto", kind=SourceKind.TWITTER),
    PackChannel("incrypted", kind=SourceKind.TWITTER),
    PackChannel("bitsmedia_ru", kind=SourceKind.TWITTER),
    PackChannel("prostocoin", kind=SourceKind.TWITTER),
    PackChannel("hashtelegraph", kind=SourceKind.TWITTER),
    PackChannel("bccnews", kind=SourceKind.TWITTER),
    PackChannel("cryptorussia", kind=SourceKind.TWITTER),
    PackChannel("profinvestment", kind=SourceKind.TWITTER),
    PackChannel("coinpost_ru", kind=SourceKind.TWITTER),
    PackChannel("ru_holderlab", kind=SourceKind.TWITTER),
    PackChannel("cryptohacker_ru", kind=SourceKind.TWITTER),
)

# Reddit crypto subreddits (TASK-093). Bare lowercased subreddit names (no `r/`),
# 3-21 of [a-z0-9_] (REDDIT_HANDLE_PATTERN). Candidates — private/dead subs are
# silently skipped by the collector; live pruning is owner-gated on Reddit creds.
_CRYPTO_REDDIT_CHANNELS: tuple[PackChannel, ...] = (
    # -- EN: broad crypto / markets --
    PackChannel("cryptocurrency", kind=SourceKind.REDDIT),  # r/CryptoCurrency — ~9M
    PackChannel("cryptomarkets", kind=SourceKind.REDDIT),  # r/CryptoMarkets
    PackChannel("bitcoin", kind=SourceKind.REDDIT),  # r/Bitcoin — ~7M
    PackChannel("bitcoinmarkets", kind=SourceKind.REDDIT),  # r/BitcoinMarkets
    PackChannel("ethereum", kind=SourceKind.REDDIT),  # r/ethereum
    PackChannel("ethtrader", kind=SourceKind.REDDIT),  # r/ethtrader
    PackChannel("ethfinance", kind=SourceKind.REDDIT),  # r/ethfinance
    PackChannel("defi", kind=SourceKind.REDDIT),  # r/defi
    PackChannel("cryptocurrencytrading", kind=SourceKind.REDDIT),  # r/CryptoCurrencyTrading
    PackChannel("altcoin", kind=SourceKind.REDDIT),  # r/altcoin
    PackChannel("crypto_com", kind=SourceKind.REDDIT),  # r/Crypto_com
    PackChannel("binance", kind=SourceKind.REDDIT),  # r/binance
    PackChannel("solana", kind=SourceKind.REDDIT),  # r/solana
    PackChannel("cardanocoin", kind=SourceKind.REDDIT),  # r/CardanoCoin
    PackChannel("monero", kind=SourceKind.REDDIT),  # r/Monero
    PackChannel("litecoin", kind=SourceKind.REDDIT),  # r/litecoin
    PackChannel("dogecoin", kind=SourceKind.REDDIT),  # r/dogecoin
    PackChannel("cryptomoonshots", kind=SourceKind.REDDIT),  # r/CryptoMoonShots
    PackChannel("satoshistreetbets", kind=SourceKind.REDDIT),  # r/SatoshiStreetBets
    PackChannel("bitcoinbeginners", kind=SourceKind.REDDIT),  # r/BitcoinBeginners
    # -- RU: scarce; validated live, dead ones pruned --
    PackChannel("bitcoin_ru", kind=SourceKind.REDDIT),  # r/Bitcoin_ru
    PackChannel("cryptocurrencyru", kind=SourceKind.REDDIT),  # r/CryptoCurrencyRU
)

# Event-overlap crypto-RU pack (TASK-128, sixth pack). Where _CRYPTO_RU_CHANNELS is
# topic-broad density (all of crypto-RU), this is a NARROW event-overlap set: news
# aggregators + origin channels (exchanges/ecosystems) that co-report ONE breaking
# event (listing, hack, regulation) within minutes → a direct, measurable driver of
# channels_count>1 on a single story. Most handles are reused verified-live from
# _CRYPTO_RU_CHANNELS (✓ via t.me/s 2026-06-13); the rest are public candidates pruned
# by the collector at read time (dead → resolve None → skip, ADR-001). Live overlap
# measurement is owner/runtime-gated (needs pool>=3, TASK-059). 20 unique handles.
_CRYPTO_RU_OVERLAP_CHANNELS: tuple[PackChannel, ...] = (
    # -- news aggregators / media (fast co-report of one event) --
    PackChannel("@forklog"),  # ForkLog ✓reused
    PackChannel("@RBCCrypto"),  # РБК Крипто ✓reused
    PackChannel("@if_market_news"),  # InvestFuture Market News ✓reused
    PackChannel("@cryptodaily"),  # Crypto Daily ✓reused
    PackChannel("@web3news"),  # Web3 News RU ✓reused
    PackChannel("@incrypted"),  # Incrypted ✓reused
    PackChannel("@bitsmedia"),  # BITS.MEDIA ✓reused
    PackChannel("@hashtelegraph"),  # Hash Telegraph ✓reused
    PackChannel("@coin_post"),  # CoinPost ✓reused
    PackChannel("@crypto_hd"),  # Crypto Headlines ✓reused
    PackChannel("@cryptodaily_ru"),  # Crypto Daily RU (candidate, verify live)
    PackChannel("@bitnovosti"),  # BitNovosti (candidate, verify live)
    PackChannel("@cryptorussia_news"),  # CryptoRussia (candidate, verify live)
    # -- origins / exchanges / ecosystem (origin channel of the event) --
    PackChannel("@binance_ru"),  # Binance Новости RU ✓reused
    PackChannel("@toncoin_rus"),  # Toncoin RUS ✓reused
    PackChannel("@tonblockchain"),  # TON Blockchain ✓reused
    PackChannel("@decenter"),  # DeCenter ✓reused
    PackChannel("@crypto_sekta"),  # Криптосекта ✓reused
    PackChannel("@bybite_ru"),  # Bybit RU (candidate, verify live)
    PackChannel("@okx_russian"),  # OKX Russian (candidate, verify live)
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
    PackDef(
        slug="crypto-twitter",
        title="Crypto Twitter (RU+EN)",
        topic="crypto",
        channels=_CRYPTO_TWITTER_CHANNELS,
    ),
    PackDef(
        slug="crypto-reddit",
        title="Crypto Reddit (RU+EN)",
        topic="crypto",
        channels=_CRYPTO_REDDIT_CHANNELS,
    ),
    PackDef(
        slug="crypto-ru-overlap",
        title="Crypto RU Overlap",
        topic="crypto",
        channels=_CRYPTO_RU_OVERLAP_CHANNELS,
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
