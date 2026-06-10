"""Unit tests for the showcase config invariant (TASK-044).

Invariant: showcase_post_delay_seconds > free_alert_delay_seconds.

The public-channel posting delay MUST exceed the Free-plan alert delay —
otherwise the channel gives away signals faster than the paid Free tier,
breaking the value ladder (Discussion, Invariants).

Tests:
- Delay > free_delay → valid (no error).
- Delay == free_delay → should raise ValidationError.
- Delay < free_delay → should raise ValidationError.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def _make_settings(**overrides: object) -> object:
    """Create a Settings instance with specific showcase/free delay values.

    Uses model_construct to bypass env lookup — all other required fields
    are set to safe test values matching the test conftest pattern.
    """
    from config import Settings

    base = {
        "jwt_secret": "test-secret",
        "oauth_state_secret": "test-state",
        "google_client_id": "test-gid",
        "google_client_secret": "test-gsecret",
        "free_alert_delay_seconds": 1800,
        "showcase_post_delay_seconds": 2400,  # valid default > 1800
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestShowcaseDelayInvariant:
    """showcase_post_delay_seconds must be > free_alert_delay_seconds."""

    def test_delay_greater_than_free_delay_valid(self) -> None:
        """showcase_post_delay > free_alert_delay → no error."""
        s = _make_settings(
            free_alert_delay_seconds=1800,
            showcase_post_delay_seconds=2400,
        )
        assert s.showcase_post_delay_seconds > s.free_alert_delay_seconds  # type: ignore[union-attr]

    def test_delay_equal_to_free_delay_raises(self) -> None:
        """showcase_post_delay == free_alert_delay → ValidationError (channel as fast as Free)."""
        with pytest.raises(ValidationError) as exc_info:
            _make_settings(
                free_alert_delay_seconds=1800,
                showcase_post_delay_seconds=1800,  # equal → invalid
            )
        assert (
            "showcase_post_delay_seconds" in str(exc_info.value)
            or "delay" in str(exc_info.value).lower()
        )

    def test_delay_less_than_free_delay_raises(self) -> None:
        """showcase_post_delay < free_alert_delay → ValidationError."""
        with pytest.raises(ValidationError):
            _make_settings(
                free_alert_delay_seconds=1800,
                showcase_post_delay_seconds=1200,  # less → invalid
            )

    def test_zero_showcase_delay_raises(self) -> None:
        """showcase_post_delay=0 is always less than free_delay → ValidationError."""
        with pytest.raises(ValidationError):
            _make_settings(
                free_alert_delay_seconds=1800,
                showcase_post_delay_seconds=0,
            )
