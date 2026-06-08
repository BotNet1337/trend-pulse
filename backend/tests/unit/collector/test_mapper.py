"""AC1 (RED anchor) — pure `map_entity(tg message, ref) -> RawPost`.

Builds a fake Telegram message entity (a plain stub, no network, no Telethon
import) and asserts the mapper produces a fully normalized `RawPost`:
correct `source`/`external_id`/`author`/`text`/`media_hashes`/`posted_at`
(tz-aware UTC) plus normalized `PostMetrics` (views/forwards/reactions) with
platform-specific data parked in `metrics.extra`.

Written FIRST; fails until `collector/telegram/mapper.py` exists (TDD RED).
"""

from datetime import UTC, datetime
from types import SimpleNamespace

from collector.base import PostMetrics, RawPost, SourceKind, SourceRef
from collector.telegram.mapper import map_entity

_REF = SourceRef(kind=SourceKind.TELEGRAM, handle="@telegram")


def _reaction(count: int) -> SimpleNamespace:
    return SimpleNamespace(count=count)


def _message(**overrides: object) -> SimpleNamespace:
    """A stub mirroring the Telethon `Message` attributes the mapper reads."""
    base = {
        "id": 4242,
        "message": "hello world",
        "views": 1000,
        "forwards": 50,
        "reactions": SimpleNamespace(results=[_reaction(7), _reaction(3)]),
        "date": datetime(2026, 6, 8, 12, 0, 0, tzinfo=UTC),
        "post_author": "Editor",
        "media": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_map_entity_returns_rawpost_with_core_fields() -> None:
    post = map_entity(_message(), _REF)

    assert isinstance(post, RawPost)
    assert post.source == _REF
    assert post.external_id == "4242"
    assert post.author == "Editor"
    assert post.text == "hello world"


def test_map_entity_normalizes_metrics() -> None:
    post = map_entity(_message(), _REF)

    assert isinstance(post.metrics, PostMetrics)
    assert post.metrics.views == 1000
    assert post.metrics.forwards == 50
    # reactions normalized to the SUM of all reaction counts (7 + 3).
    assert post.metrics.reactions == 10


def test_map_entity_posted_at_is_tz_aware_utc() -> None:
    post = map_entity(_message(), _REF)

    assert post.posted_at.tzinfo is not None
    assert post.posted_at.utcoffset() == UTC.utcoffset(None)


def test_map_entity_coerces_naive_datetime_to_utc() -> None:
    naive = datetime(2026, 6, 8, 12, 0, 0)
    post = map_entity(_message(date=naive), _REF)

    assert post.posted_at.tzinfo is not None
    assert post.posted_at.utcoffset() == UTC.utcoffset(None)


def test_map_entity_missing_metrics_default_to_zero_not_none() -> None:
    post = map_entity(_message(views=None, forwards=None, reactions=None), _REF)

    assert post.metrics.views == 0
    assert post.metrics.forwards == 0
    assert post.metrics.reactions == 0


def test_map_entity_text_only_media_yields_empty_text() -> None:
    post = map_entity(_message(message=None), _REF)

    assert post.text == ""


def test_map_entity_extra_carries_platform_specifics() -> None:
    post = map_entity(_message(), _REF)

    # platform-specific numeric extras live in metrics.extra (e.g. reaction kinds).
    assert "reaction_kinds" in post.metrics.extra
    assert post.metrics.extra["reaction_kinds"] == 2
