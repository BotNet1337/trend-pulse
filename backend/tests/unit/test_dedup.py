"""AC1 — dedup collapses near-duplicate texts (MinHash), input never mutated.

RED-anchor for TASK-007: written before `pipeline.steps.dedup` exists. Builds
platform-independent `RawPost` fixtures (no Telegram) so the step is exercised on
the ADR-001 contract alone.
"""

from collections.abc import Mapping
from datetime import UTC, datetime

from collector.base import PostMetrics, RawPost, SourceKind, SourceRef
from pipeline.steps import dedup


def _post(external_id: str, text: str) -> RawPost:
    return RawPost(
        source=SourceRef(kind=SourceKind.TELEGRAM, handle="@chan"),
        external_id=external_id,
        author="author",
        text=text,
        media_hashes=(),
        metrics=PostMetrics(views=10, forwards=1, reactions=2),
        posted_at=datetime(2026, 6, 8, tzinfo=UTC),
    )


_BASE_TEXT = (
    "Breaking news: the central bank raised interest rates by half a point today "
    "citing persistent inflation across the broader economy this quarter"
)
_NEAR_TEXT = (
    "Breaking news: the central bank raised interest rates by half a point today "
    "citing persistent inflation across the broader economy this quarter!!"
)
_OTHER_TEXT = (
    "A new indie video game about gardening on a tiny floating island just won "
    "three awards at the annual festival and fans are thrilled with the soundtrack"
)


def test_dedup_collapses_near_duplicate_keeps_distinct() -> None:
    p1 = _post("1", _BASE_TEXT)
    p1_near = _post("2", _NEAR_TEXT)
    p2 = _post("3", _OTHER_TEXT)

    result = dedup.run([p1, p1_near, p2])

    # Near-duplicate pair collapses to one; the distinct post is kept → 2 total.
    assert len(result) == 2
    kept_ids = {p.external_id for p in result}
    # First of the near-dup pair is kept (p1), the distinct post (p2) survives.
    assert "1" in kept_ids
    assert "3" in kept_ids
    assert "2" not in kept_ids


def test_dedup_does_not_mutate_input() -> None:
    p1 = _post("1", _BASE_TEXT)
    p1_near = _post("2", _NEAR_TEXT)
    p2 = _post("3", _OTHER_TEXT)
    original = [p1, p1_near, p2]
    snapshot = list(original)

    dedup.run(original)

    # Input list object and its members are untouched (immutability invariant).
    assert original == snapshot
    assert original[0] is p1
    assert original[1] is p1_near
    assert original[2] is p2


def test_dedup_empty_input_returns_empty() -> None:
    assert dedup.run([]) == []


def test_dedup_single_post_passthrough() -> None:
    p1 = _post("1", _BASE_TEXT)
    result = dedup.run([p1])
    assert len(result) == 1
    assert result[0] is p1


def test_dedup_returns_new_list() -> None:
    p1 = _post("1", _BASE_TEXT)
    posts = [p1]
    result = dedup.run(posts)
    # New list object, not the same reference (pure step).
    assert result is not posts


def test_dedup_handles_none_and_empty_text() -> None:
    empty = _post("1", "")
    none_text = RawPost(
        source=SourceRef(kind=SourceKind.TELEGRAM, handle="@chan"),
        external_id="2",
        author=None,
        text=None,
        media_hashes=(),
        metrics=PostMetrics(views=0, forwards=0, reactions=0, extra={}),
        posted_at=datetime(2026, 6, 8, tzinfo=UTC),
    )
    other = _post("3", _OTHER_TEXT)
    # Must not raise on empty/None text; distinct posts are kept.
    result = dedup.run([empty, none_text, other])
    assert len(result) >= 1
    assert isinstance(result, list)
    # extra mapping survives untouched on the kept posts (sanity on RawPost shape).
    assert isinstance(none_text.metrics.extra, Mapping)
