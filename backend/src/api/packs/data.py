"""Curated channel pack catalog — static, immutable definitions (TASK-038).

The catalog is the single source of truth for pack slugs, titles, topics, and
the list of Telegram handles. Changes require a PR + review (no admin UI).

OWNER NOTE: The Telegram handles listed here are PLACEHOLDER EXAMPLES.
The product/content owner must curate the final list of real, high-quality
channels before the first production deployment. Handles follow the format
validated by `TELEGRAM_HANDLE_PATTERN` (watchlist/schemas.py): '@' + 4-32 of
[A-Za-z0-9_]. Dead handles are silently skipped by the collector (ADR-001).

Two packs are required by TASK-038 as a baseline:
  - crypto-ru  (~8 handles): Russian-language crypto / DeFi channels
  - tech-en    (~6 handles): English-language tech / startup channels

Known limitation (by design, task doc §Discussion): subscribing a pack snapshot
the current handle list; if a pack is updated later, users must unsubscribe and
re-subscribe to get the new channels (no auto-sync, no migration).
"""

from dataclasses import dataclass

from storage.models.channels import SourceKind

# ─── Default alert config for pack-subscribed watchlist rows ─────────────────

# These are the defaults applied to EVERY watchlist row created by a pack
# subscribe. Users may update individual rows afterwards via PATCH /watchlists.
_DEFAULT_SCORE_THRESHOLD = 70
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

# OWNER: Replace placeholder handles with real, curated channel usernames.
# Each handle must be a valid Telegram @username (4-32 chars of [A-Za-z0-9_]).
# Verify channels are public and active before adding them.

_CRYPTO_RU_CHANNELS: tuple[PackChannel, ...] = (
    # Russian-language crypto / DeFi / Web3 channels (curated by owner)
    PackChannel("@cryptovalute"),  # [PLACEHOLDER] crypto news RU
    PackChannel("@coin_post"),  # [PLACEHOLDER] coin analytics RU
    PackChannel("@bits_media"),  # [PLACEHOLDER] crypto media RU
    PackChannel("@defi_rus"),  # [PLACEHOLDER] DeFi RU community
    PackChannel("@blockchain_rus"),  # [PLACEHOLDER] blockchain RU
    PackChannel("@crypto_invest_ru"),  # [PLACEHOLDER] crypto investing RU
    PackChannel("@nft_russia"),  # [PLACEHOLDER] NFT RU market
    PackChannel("@web3_community"),  # [PLACEHOLDER] Web3 RU builders
)

_TECH_EN_CHANNELS: tuple[PackChannel, ...] = (
    # English-language tech / startup / AI channels (curated by owner)
    PackChannel("@techcrunch_feed"),  # [PLACEHOLDER] TechCrunch news
    PackChannel("@hackernewsfeed"),  # [PLACEHOLDER] HN-style tech
    PackChannel("@aistartups"),  # [PLACEHOLDER] AI startup news
    PackChannel("@siliconvalleytech"),  # [PLACEHOLDER] SV news & funding
    PackChannel("@productdrop"),  # [PLACEHOLDER] product launches
    PackChannel("@opensourcetech"),  # [PLACEHOLDER] open-source highlights
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
