"""AC2 — normalize is pure/immutable and cleans text."""

from datetime import UTC, datetime

from collector.base import PostMetrics, RawPost, SourceKind, SourceRef
from pipeline.steps import normalize
from pipeline.steps.normalize import NormalizedPost


def _post(text: str | None) -> RawPost:
    return RawPost(
        source=SourceRef(kind=SourceKind.TELEGRAM, handle="@chan"),
        external_id="1",
        author="author",
        text=text,
        media_hashes=(),
        metrics=PostMetrics(views=10, forwards=1, reactions=2),
        posted_at=datetime(2026, 6, 8, tzinfo=UTC),
    )


def test_normalize_strips_urls_markup_emoji() -> None:
    dirty = "**Big** news! Visit https://t.me/foo now 🚀🔥 _read more_ at www.x.com"
    result = normalize.run([_post(dirty)])
    assert len(result) == 1
    cleaned = result[0].text
    assert "https://" not in cleaned
    assert "www." not in cleaned
    assert "*" not in cleaned
    assert "_" not in cleaned
    assert "🚀" not in cleaned
    assert "🔥" not in cleaned
    assert "Big news!" in cleaned
    # Whitespace collapsed, trimmed.
    assert "  " not in cleaned
    assert cleaned == cleaned.strip()


def test_normalize_returns_new_immutable_objects() -> None:
    post = _post("**hello** http://t.me/x")
    original_text = post.text
    result = normalize.run([post])
    # Input RawPost is untouched (frozen anyway, but assert the value is unchanged).
    assert post.text == original_text
    assert isinstance(result[0], NormalizedPost)
    # NormalizedPost is frozen.
    assert type(result[0]).__dataclass_params__.frozen is True
    # Carries provenance + metrics + posted_at.
    assert result[0].source is post.source
    assert result[0].external_id == post.external_id
    assert result[0].metrics is post.metrics
    assert result[0].posted_at == post.posted_at


def test_normalize_returns_new_list() -> None:
    posts = [_post("hi")]
    result = normalize.run(posts)
    assert result is not posts


def test_normalize_empty_and_none_text() -> None:
    result = normalize.run([_post(None), _post(""), _post("   "), _post("🚀🔥")])
    # None/empty/whitespace/emoji-only → empty cleaned text; must not raise.
    assert all(p.text == "" for p in result)


def test_normalize_empty_input() -> None:
    assert normalize.run([]) == []
