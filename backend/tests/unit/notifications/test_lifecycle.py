"""RED→GREEN anchor (TASK-069): lifecycle-email pure logic.

Covers:
  - `is_digest_due` — verification gate, opt-out gate, 7d window, NULL last-sent.
  - `is_winback_due` — verification/opt-out gates, watchlist requirement,
    inactivity surrogate (MAX(delivered_at) older than 14d or no alerts),
    one-per-cycle + 30d cooldown, re-arm on new activity.
  - unsubscribe token — round-trip, tampering, wrong audience, expiry, garbage.

All functions are pure (no DB) — this file runs under `make ci-fast`.
Anti-spam invariants here are the core of the task: lifecycle emails NEVER go
to unverified or opted-out users, and never more often than the limits.
"""

from datetime import UTC, datetime, timedelta

import pytest

from config import Settings

# Fixed "now" for deterministic window math.
_NOW = datetime(2026, 6, 11, 12, 0, 0, tzinfo=UTC)

_DIGEST_PERIOD_DAYS = 7
_WINBACK_INACTIVE_DAYS = 14
_WINBACK_COOLDOWN_DAYS = 30


def _make_settings(**overrides: object) -> Settings:
    """Settings with test-safe secrets (pattern: tests/unit/test_email.py)."""
    defaults: dict[str, object] = dict(
        jwt_secret="test-secret",
        oauth_state_secret="test-oauth-secret",
        google_client_id="test-gci",
        google_client_secret="test-gcs",
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# is_digest_due
# ---------------------------------------------------------------------------


class TestIsDigestDue:
    def _due(self, **overrides: object) -> bool:
        from notifications.lifecycle import is_digest_due

        kwargs: dict[str, object] = dict(
            now=_NOW,
            is_verified=True,
            opt_out=False,
            digest_last_sent_at=None,
            period_days=_DIGEST_PERIOD_DAYS,
        )
        kwargs.update(overrides)
        return is_digest_due(**kwargs)  # type: ignore[arg-type]

    def test_never_sent_is_due(self) -> None:
        assert self._due(digest_last_sent_at=None) is True

    def test_unverified_never_due(self) -> None:
        """AC5 anti-spam: unverified users get NOTHING lifecycle."""
        assert self._due(is_verified=False) is False

    def test_opted_out_never_due(self) -> None:
        """AC4: opt-out blocks the digest."""
        assert self._due(opt_out=True) is False

    def test_sent_within_window_not_due(self) -> None:
        """AC2: a second tick the same day must NOT resend."""
        assert self._due(digest_last_sent_at=_NOW - timedelta(hours=2)) is False

    def test_sent_just_under_window_not_due(self) -> None:
        last = _NOW - timedelta(days=_DIGEST_PERIOD_DAYS) + timedelta(minutes=1)
        assert self._due(digest_last_sent_at=last) is False

    def test_sent_exactly_window_ago_is_due(self) -> None:
        last = _NOW - timedelta(days=_DIGEST_PERIOD_DAYS)
        assert self._due(digest_last_sent_at=last) is True

    def test_sent_long_ago_is_due(self) -> None:
        assert self._due(digest_last_sent_at=_NOW - timedelta(days=30)) is True


# ---------------------------------------------------------------------------
# is_winback_due
# ---------------------------------------------------------------------------


class TestIsWinbackDue:
    def _due(self, **overrides: object) -> bool:
        from notifications.lifecycle import is_winback_due

        kwargs: dict[str, object] = dict(
            now=_NOW,
            is_verified=True,
            opt_out=False,
            has_watchlist=True,
            last_delivered_at=None,
            winback_last_sent_at=None,
            inactive_days=_WINBACK_INACTIVE_DAYS,
            cooldown_days=_WINBACK_COOLDOWN_DAYS,
        )
        kwargs.update(overrides)
        return is_winback_due(**kwargs)  # type: ignore[arg-type]

    def test_no_alerts_with_watchlist_is_due(self) -> None:
        """AC3: 'или алертов нет вовсе' counts as inactive."""
        assert self._due(last_delivered_at=None) is True

    def test_unverified_never_due(self) -> None:
        assert self._due(is_verified=False) is False

    def test_opted_out_never_due(self) -> None:
        assert self._due(opt_out=True) is False

    def test_no_watchlist_never_due(self) -> None:
        """Edge case: nothing to win the user back to — skip."""
        assert self._due(has_watchlist=False) is False

    def test_recent_activity_not_due(self) -> None:
        recent = _NOW - timedelta(days=_WINBACK_INACTIVE_DAYS - 1)
        assert self._due(last_delivered_at=recent) is False

    def test_inactive_past_threshold_is_due(self) -> None:
        stale = _NOW - timedelta(days=_WINBACK_INACTIVE_DAYS, hours=1)
        assert self._due(last_delivered_at=stale) is True

    def test_already_sent_same_cycle_not_due(self) -> None:
        """One win-back per inactivity cycle: no resend without new activity."""
        stale = _NOW - timedelta(days=60)
        sent = _NOW - timedelta(days=40)  # cooldown elapsed, but same cycle
        assert self._due(last_delivered_at=stale, winback_last_sent_at=sent) is False

    def test_rearmed_but_cooldown_active_not_due(self) -> None:
        """New cycle (activity after last win-back) but <30d since send → wait."""
        sent = _NOW - timedelta(days=20)
        new_activity = _NOW - timedelta(days=15)  # newer than sent → re-armed
        assert self._due(last_delivered_at=new_activity, winback_last_sent_at=sent) is False

    def test_rearmed_and_cooldown_elapsed_is_due(self) -> None:
        """Re-arm + 30d cooldown both satisfied → second win-back allowed."""
        sent = _NOW - timedelta(days=40)
        new_activity = _NOW - timedelta(days=35)  # after send, then inactive 35d
        assert self._due(last_delivered_at=new_activity, winback_last_sent_at=sent) is True

    def test_never_sent_no_activity_is_due_once(self) -> None:
        assert self._due(last_delivered_at=None, winback_last_sent_at=None) is True

    def test_sent_never_rearmed_no_activity_not_due(self) -> None:
        """No alerts ever + win-back already sent → same cycle forever."""
        sent = _NOW - timedelta(days=90)
        assert self._due(last_delivered_at=None, winback_last_sent_at=sent) is False


# ---------------------------------------------------------------------------
# Unsubscribe token
# ---------------------------------------------------------------------------


class TestUnsubscribeToken:
    def test_round_trip(self) -> None:
        from notifications.lifecycle import (
            generate_unsubscribe_token,
            parse_unsubscribe_token,
        )

        settings = _make_settings()
        token = generate_unsubscribe_token(42, settings=settings)
        assert parse_unsubscribe_token(token, settings=settings) == 42

    def test_garbage_rejected(self) -> None:
        from notifications.lifecycle import (
            UnsubscribeTokenError,
            parse_unsubscribe_token,
        )

        with pytest.raises(UnsubscribeTokenError):
            parse_unsubscribe_token("not-a-jwt", settings=_make_settings())

    def test_tampered_signature_rejected(self) -> None:
        from notifications.lifecycle import (
            UnsubscribeTokenError,
            generate_unsubscribe_token,
            parse_unsubscribe_token,
        )

        settings = _make_settings()
        token = generate_unsubscribe_token(42, settings=settings)
        other = _make_settings(jwt_secret="different-secret")
        with pytest.raises(UnsubscribeTokenError):
            parse_unsubscribe_token(token, settings=other)

    def test_wrong_audience_rejected(self) -> None:
        """An auth JWT (fastapi-users audience) must NOT unsubscribe anyone."""
        from fastapi_users.jwt import generate_jwt

        from notifications.lifecycle import (
            UnsubscribeTokenError,
            parse_unsubscribe_token,
        )

        settings = _make_settings()
        foreign = generate_jwt(
            {"sub": "42", "aud": "fastapi-users:auth"},
            settings.jwt_secret,
            lifetime_seconds=3600,
        )
        with pytest.raises(UnsubscribeTokenError):
            parse_unsubscribe_token(foreign, settings=settings)

    def test_expired_rejected(self) -> None:
        from fastapi_users.jwt import generate_jwt

        from notifications.lifecycle import (
            UNSUBSCRIBE_TOKEN_AUDIENCE,
            UnsubscribeTokenError,
            parse_unsubscribe_token,
        )

        settings = _make_settings()
        expired = generate_jwt(
            {
                "sub": "42",
                "aud": UNSUBSCRIBE_TOKEN_AUDIENCE,
                "exp": datetime.now(UTC) - timedelta(seconds=10),
            },
            settings.jwt_secret,
        )
        with pytest.raises(UnsubscribeTokenError):
            parse_unsubscribe_token(expired, settings=settings)

    def test_non_numeric_sub_rejected(self) -> None:
        from fastapi_users.jwt import generate_jwt

        from notifications.lifecycle import (
            UNSUBSCRIBE_TOKEN_AUDIENCE,
            UnsubscribeTokenError,
            parse_unsubscribe_token,
        )

        settings = _make_settings()
        bad = generate_jwt(
            {"sub": "robert'); DROP TABLE users;--", "aud": UNSUBSCRIBE_TOKEN_AUDIENCE},
            settings.jwt_secret,
            lifetime_seconds=3600,
        )
        with pytest.raises(UnsubscribeTokenError):
            parse_unsubscribe_token(bad, settings=settings)


# ---------------------------------------------------------------------------
# Unsubscribe URL builder
# ---------------------------------------------------------------------------


class TestUnsubscribeUrl:
    def test_uses_public_base_url_when_set(self) -> None:
        from notifications.lifecycle import build_unsubscribe_url

        settings = _make_settings(public_base_url="https://foresignal.biz")
        url = build_unsubscribe_url(7, settings=settings)
        assert url.startswith("https://foresignal.biz/api/v1/email/unsubscribe?token=")

    def test_falls_back_to_frontend_base_url(self) -> None:
        from notifications.lifecycle import build_unsubscribe_url

        settings = _make_settings(public_base_url="", frontend_base_url="http://localhost")
        url = build_unsubscribe_url(7, settings=settings)
        assert url.startswith("http://localhost/api/v1/email/unsubscribe?token=")
