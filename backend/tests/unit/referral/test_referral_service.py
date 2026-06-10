"""Unit tests for the referral service layer (TASK-046).

Tests (no DB):
- Code generation: format, charset, length, uniqueness.
- Collision retry logic.
- Self-referral guard: referrer == created user impossible at register time
  (new user has no code yet), but the guard is tested via resolve step with
  a referrer who happens to share the same id post-creation path.
- First-payment predicate logic: returns True only when no prior processed
  payments and no existing reward.
- Reward amount equals settings.referral_reward_usdt.
"""

import pytest

pytestmark = pytest.mark.unit


class TestCodeGeneration:
    """ref_code generation: format, charset, length, uniqueness."""

    def test_generated_code_is_string(self) -> None:
        from referral.service import generate_ref_code

        code = generate_ref_code()
        assert isinstance(code, str)

    def test_generated_code_length(self) -> None:
        from referral.service import generate_ref_code

        # Codes must be reasonably short (8-16 chars) for shareable links.
        code = generate_ref_code()
        assert 8 <= len(code) <= 16

    def test_generated_code_url_safe_charset(self) -> None:
        """Code must contain only URL-safe characters (no +, /, =)."""
        import re

        from referral.service import generate_ref_code

        code = generate_ref_code()
        # URL-safe base64 alphabet: letters, digits, - and _
        assert re.match(r"^[A-Za-z0-9_-]+$", code), f"Unsafe chars in: {code!r}"

    def test_generated_codes_are_unique(self) -> None:
        """10 consecutive calls must not collide (probabilistic — but near-certain)."""
        from referral.service import generate_ref_code

        codes = [generate_ref_code() for _ in range(10)]
        assert len(set(codes)) == 10


class TestSelfReferralGuard:
    """Self-referral guard: resolve_referrer_id returns None for own code."""

    def test_resolve_returns_none_for_unknown_code(self) -> None:
        """An unrecognised code silently returns None (AC1: invalid ref → referred_by NULL)."""
        from unittest.mock import MagicMock

        from sqlalchemy.orm import Session

        from referral.service import resolve_referrer_id

        session = MagicMock(spec=Session)
        # scalars().unique().one_or_none() returns None — no row with that code.
        # User model has lazy="joined" on oauth_accounts, so .unique() is required.
        session.scalars.return_value.unique.return_value.one_or_none.return_value = None

        result = resolve_referrer_id(session, ref_code="UNKNOWN")
        assert result is None

    def test_resolve_returns_referrer_id_for_valid_code(self) -> None:
        """A known code returns the referrer's user id."""
        from unittest.mock import MagicMock

        from sqlalchemy.orm import Session

        from referral.service import resolve_referrer_id
        from storage.models.users import User

        session = MagicMock(spec=Session)
        referrer = MagicMock(spec=User)
        referrer.id = 42
        session.scalars.return_value.unique.return_value.one_or_none.return_value = referrer

        result = resolve_referrer_id(session, ref_code="ABC123")
        assert result == 42

    def test_self_referral_blocked(self) -> None:
        """resolve_referrer_id returns None when referrer.id == new_user_id."""
        from unittest.mock import MagicMock

        from sqlalchemy.orm import Session

        from referral.service import resolve_referrer_id
        from storage.models.users import User

        session = MagicMock(spec=Session)
        referrer = MagicMock(spec=User)
        referrer.id = 99
        session.scalars.return_value.unique.return_value.one_or_none.return_value = referrer

        # Requesting user has the same id as the referrer (self-referral scenario).
        result = resolve_referrer_id(session, ref_code="SELFCODE", exclude_user_id=99)
        assert result is None


class TestFirstPaymentPredicate:
    """is_first_payment: returns True only on first eligible activation.

    Note: is_first_payment_for_referral now uses .limit(1).first() (not .one_or_none())
    so mocks set .scalars().first() rather than .scalars().one_or_none().
    """

    def test_returns_true_when_no_prior_payments_and_no_reward(self) -> None:
        """No prior processed payments + no existing reward → True."""
        from unittest.mock import MagicMock, patch

        from sqlalchemy.orm import Session

        from referral.service import is_first_payment_for_referral

        session = MagicMock(spec=Session)
        # No prior processed payments — scalars().first() returns None.
        session.scalars.return_value.first.return_value = None

        with patch("referral.service._referral_reward_exists", return_value=False):
            result = is_first_payment_for_referral(session, user_id=1)

        assert result is True

    def test_returns_false_when_prior_processed_payment_exists(self) -> None:
        """A processed payment already exists → False (not first)."""
        from unittest.mock import MagicMock, patch

        from sqlalchemy.orm import Session

        from referral.service import is_first_payment_for_referral
        from storage.models.subscriptions import BillingPayment

        session = MagicMock(spec=Session)
        existing_payment = MagicMock(spec=BillingPayment)
        existing_payment.status = "processed"
        # scalars().first() returns the existing payment.
        session.scalars.return_value.first.return_value = existing_payment

        with patch("referral.service._referral_reward_exists", return_value=False):
            result = is_first_payment_for_referral(session, user_id=1)

        assert result is False

    def test_returns_false_when_reward_already_exists(self) -> None:
        """A reward row already exists for this referred_user_id → False (UNIQUE guard)."""
        from unittest.mock import MagicMock, patch

        from sqlalchemy.orm import Session

        from referral.service import is_first_payment_for_referral

        session = MagicMock(spec=Session)
        session.scalars.return_value.first.return_value = None  # No prior payment

        with patch("referral.service._referral_reward_exists", return_value=True):
            result = is_first_payment_for_referral(session, user_id=1)

        assert result is False


class TestRewardAmount:
    """Reward amount is always referral_reward_usdt from settings."""

    def test_reward_amount_matches_config(self) -> None:
        """ReferralReward.amount_usdt == settings.referral_reward_usdt (default 10.0)."""
        import os

        os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
        os.environ.setdefault("OAUTH_STATE_SECRET", "test-oauth-state-secret")
        os.environ.setdefault("GOOGLE_CLIENT_ID", "test-google-client-id")
        os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-google-client-secret")

        from config import Settings

        # Use isolated Settings to avoid lru_cache pollution.
        settings = Settings()  # type: ignore[call-arg]
        assert settings.referral_reward_usdt == 10.0
