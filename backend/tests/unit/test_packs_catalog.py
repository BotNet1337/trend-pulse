"""Unit tests: packs catalog validation (TASK-038).

Tests:
- data.py catalog: unique slugs, valid handle format, non-empty.
- PackDef and PackChannel are frozen dataclasses (immutability CONVENTIONS).
- get_pack() returns correct entry or None for unknown slug.
"""

import re

from api.packs.data import PACK_CATALOG, PackChannel, PackDef, get_pack, list_packs

# Telegram handle pattern (mirrors watchlist/schemas.py TELEGRAM_HANDLE_PATTERN).
_TELEGRAM_HANDLE_RE = re.compile(r"^@[A-Za-z0-9_]{4,32}$")


# ─── Catalog structure tests ──────────────────────────────────────────────────


def test_catalog_has_at_least_two_packs() -> None:
    packs = list_packs()
    assert len(packs) >= 2, "catalog must have at least 2 packs"


def test_catalog_slugs_are_unique() -> None:
    slugs = [p.slug for p in PACK_CATALOG]
    assert len(slugs) == len(set(slugs)), f"duplicate slugs found: {slugs}"


def test_catalog_contains_crypto_ru() -> None:
    slugs = {p.slug for p in PACK_CATALOG}
    assert "crypto-ru" in slugs


def test_catalog_contains_tech_en() -> None:
    slugs = {p.slug for p in PACK_CATALOG}
    assert "tech-en" in slugs


def test_all_packs_have_channels() -> None:
    for pack in PACK_CATALOG:
        assert len(pack.channels) > 0, f"pack {pack.slug!r} must have at least one channel"


def test_all_handles_match_telegram_format() -> None:
    for pack in PACK_CATALOG:
        for ch in pack.channels:
            assert _TELEGRAM_HANDLE_RE.match(ch.handle), (
                f"handle {ch.handle!r} in pack {pack.slug!r} does not match Telegram format"
            )


def test_all_pack_fields_non_empty() -> None:
    for pack in PACK_CATALOG:
        assert pack.slug, f"pack {pack!r} has empty slug"
        assert pack.title, f"pack {pack.slug!r} has empty title"
        assert pack.topic, f"pack {pack.slug!r} has empty topic"


def test_get_pack_returns_correct_pack() -> None:
    pack = get_pack("crypto-ru")
    assert pack is not None
    assert pack.slug == "crypto-ru"
    assert pack.title == "Crypto RU"


def test_get_pack_returns_none_for_unknown_slug() -> None:
    result = get_pack("nonexistent-pack-slug")
    assert result is None


def test_pack_def_is_frozen_dataclass() -> None:
    """PackDef must be declared as a frozen dataclass (CONVENTIONS: immutability).

    We inspect the dataclass parameters directly rather than attempting mutation,
    which avoids both the FrozenInstanceError bypass via object.__setattr__ and
    any type-ignore annotations.
    """
    import dataclasses

    assert dataclasses.is_dataclass(PackDef), "PackDef must be a dataclass"
    # dataclasses.fields() only works on frozen classes; inspect __dataclass_params__
    params = PackDef.__dataclass_params__  # pyright: ignore[reportAttributeAccessIssue]
    assert params.frozen, "PackDef must have frozen=True"


def test_pack_channel_is_frozen_dataclass() -> None:
    """PackChannel must be declared as a frozen dataclass (CONVENTIONS: immutability)."""
    import dataclasses

    assert dataclasses.is_dataclass(PackChannel), "PackChannel must be a dataclass"
    params = PackChannel.__dataclass_params__  # pyright: ignore[reportAttributeAccessIssue]
    assert params.frozen, "PackChannel must have frozen=True"


def test_crypto_ru_has_enough_channels() -> None:
    pack = get_pack("crypto-ru")
    assert pack is not None
    assert len(pack.channels) >= 6, "crypto-ru should have at least 6 channels"


def test_tech_en_has_enough_channels() -> None:
    pack = get_pack("tech-en")
    assert pack is not None
    assert len(pack.channels) >= 4, "tech-en should have at least 4 channels"
