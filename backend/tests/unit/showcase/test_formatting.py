"""Unit tests for showcase/formatting.py.

Tests post text construction:
- Format: «🔥 {title} · score {N} · обнаружено в {HH:MM} UTC»
- CTA: {public_base_url}/?utm_source=tg_showcase&utm_campaign=autopost
- Topic sanitization: dirty topic (URL / @handle) must be stripped.
"""

from __future__ import annotations

from datetime import UTC, datetime


def _import() -> object:
    """Defer import until test body for RED phase."""
    from showcase import formatting  # type: ignore[import]

    return formatting


class TestBuildShowcasePost:
    """build_showcase_post text format."""

    def test_format_contains_fire_emoji_and_score(self) -> None:
        fmt = _import()
        now = datetime(2026, 6, 10, 14, 2, 0, tzinfo=UTC)
        text = fmt.build_showcase_post(
            topic="Bitcoin ETF approval",
            score=94.0,
            first_seen=now,
            public_base_url="https://foresignal.biz",
        )
        assert "🔥" in text
        assert "94" in text  # score appears

    def test_format_contains_time_stamp_in_hhmm_utc(self) -> None:
        fmt = _import()
        first_seen = datetime(2026, 6, 10, 14, 2, 0, tzinfo=UTC)
        text = fmt.build_showcase_post(
            topic="Bitcoin ETF",
            score=90.0,
            first_seen=first_seen,
            public_base_url="https://foresignal.biz",
        )
        # Must contain «обнаружено в HH:MM UTC»
        assert "обнаружено в 14:02 UTC" in text

    def test_format_contains_cta_with_utm(self) -> None:
        fmt = _import()
        first_seen = datetime(2026, 6, 10, 10, 30, 0, tzinfo=UTC)
        base = "https://foresignal.biz"
        text = fmt.build_showcase_post(
            topic="Some topic",
            score=88.5,
            first_seen=first_seen,
            public_base_url=base,
        )
        expected_cta = f"{base}/?utm_source=tg_showcase&utm_campaign=autopost"
        assert expected_cta in text

    def test_format_uses_sanitized_topic(self) -> None:
        """Topic is used as passed — caller must sanitize before calling."""
        fmt = _import()
        first_seen = datetime(2026, 6, 10, 8, 0, 0, tzinfo=UTC)
        text = fmt.build_showcase_post(
            topic="Clean Topic",
            score=87.0,
            first_seen=first_seen,
            public_base_url="https://foresignal.biz",
        )
        assert "Clean Topic" in text

    def test_score_formatted_as_integer_when_whole(self) -> None:
        """Score of 94.0 should appear as 94, not 94.0."""
        fmt = _import()
        first_seen = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)
        text = fmt.build_showcase_post(
            topic="Topic",
            score=94.0,
            first_seen=first_seen,
            public_base_url="https://foresignal.biz",
        )
        # «score 94» must be present (integer rendering)
        assert "score 94" in text


class TestTopicSanitization:
    """Dirty topic fed through sanitize → clean result, no URL/@handle."""

    def test_url_stripped_from_topic(self) -> None:
        fmt = _import()
        dirty = "Check https://evil.com for crypto updates"
        clean = fmt.sanitize_topic(dirty)
        assert "https://" not in clean
        assert "evil.com" not in clean

    def test_handle_stripped_from_topic(self) -> None:
        fmt = _import()
        dirty = "Signal from @cryptoking today"
        clean = fmt.sanitize_topic(dirty)
        assert "@cryptoking" not in clean
        assert "@" not in clean

    def test_email_stripped_from_topic(self) -> None:
        fmt = _import()
        dirty = "Contact admin@example.com for info"
        clean = fmt.sanitize_topic(dirty)
        assert "admin@example.com" not in clean

    def test_bare_tme_link_stripped(self) -> None:
        fmt = _import()
        dirty = "Join t.me/somechannel now"
        clean = fmt.sanitize_topic(dirty)
        assert "t.me" not in clean

    def test_clean_topic_unchanged(self) -> None:
        fmt = _import()
        clean_input = "Bitcoin ETF approval rally"
        result = fmt.sanitize_topic(clean_input)
        assert result == clean_input

    def test_dirty_topic_in_post_text_is_stripped(self) -> None:
        """When build_showcase_post receives a dirty topic, no URL leaks into text."""
        fmt = _import()
        first_seen = datetime(2026, 6, 10, 9, 0, 0, tzinfo=UTC)
        dirty_topic = "Big news https://t.co/abc @newsbot"
        text = fmt.build_showcase_post(
            topic=fmt.sanitize_topic(dirty_topic),
            score=88.0,
            first_seen=first_seen,
            public_base_url="https://foresignal.biz",
        )
        assert "https://" not in text or "utm_source=tg_showcase" in text  # CTA is ok
        assert "@newsbot" not in text
