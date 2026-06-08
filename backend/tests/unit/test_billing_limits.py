"""AC7/AC8 — plan-limit enforcement (DB-free; mocked usage + subscription).

Covers: channel cap per plan (Free 5 / Pro 100 / Team 500), boolean feature gating
(webhook_delivery / api_access → 403), unlimited (`None`) always passes, and the
expiry rollback (an expired Pro subscription → effective Free).

The single entry under test is `billing.assert_within_limit`; `effective_plan`
resolves the rollback. The session is mocked so these stay unit tests.
"""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from billing.limits import PlanLimitExceeded, assert_within_limit, effective_plan
from billing.plans import Plan, Resource
from storage.models.base import utcnow
from storage.models.subscriptions import Subscription
from storage.models.users import User


def _user(plan: str = "free", user_id: int = 1) -> User:
    user = User()
    user.id = user_id
    user.plan = plan
    return user


def _session_with(*, usage: int = 0, subscription: Subscription | None = None) -> MagicMock:
    """Mock session: `scalar` returns a usage count, `scalars().one_or_none()` a sub."""
    session = MagicMock()
    session.scalar.return_value = usage
    scalars_result = MagicMock()
    scalars_result.one_or_none.return_value = subscription
    session.scalars.return_value = scalars_result
    return session


def _active_sub(plan: Plan) -> Subscription:
    return Subscription(user_id=1, plan=plan.value, expires_at=utcnow() + timedelta(days=10))


def _expired_sub(plan: Plan) -> Subscription:
    return Subscription(user_id=1, plan=plan.value, expires_at=utcnow() - timedelta(days=1))


# --- AC7: channel cap per plan ---


def test_free_channels_under_cap_passes() -> None:
    session = _session_with(usage=4)
    assert_within_limit(session, _user("free"), Resource.CHANNELS)  # 5th allowed


def test_free_channels_at_cap_raises_402() -> None:
    session = _session_with(usage=5)  # 6th would breach Free cap 5
    with pytest.raises(PlanLimitExceeded) as exc:
        assert_within_limit(session, _user("free"), Resource.CHANNELS)
    assert exc.value.code == 402


def test_pro_channels_within_higher_cap_passes() -> None:
    session = _session_with(usage=6, subscription=_active_sub(Plan.PRO))
    assert_within_limit(session, _user("pro"), Resource.CHANNELS)  # Pro cap 100


def test_team_channels_within_highest_cap_passes() -> None:
    session = _session_with(usage=200, subscription=_active_sub(Plan.TEAM))
    assert_within_limit(session, _user("team"), Resource.CHANNELS)  # Team cap 500


# --- AC8: feature gating ---


def test_free_webhook_delivery_forbidden_403() -> None:
    session = _session_with()
    with pytest.raises(PlanLimitExceeded) as exc:
        assert_within_limit(session, _user("free"), Resource.WEBHOOK_DELIVERY)
    assert exc.value.code == 403


def test_pro_webhook_delivery_allowed() -> None:
    session = _session_with(subscription=_active_sub(Plan.PRO))
    assert_within_limit(session, _user("pro"), Resource.WEBHOOK_DELIVERY)


def test_free_api_access_forbidden_403() -> None:
    session = _session_with()
    with pytest.raises(PlanLimitExceeded) as exc:
        assert_within_limit(session, _user("free"), Resource.API_ACCESS)
    assert exc.value.code == 403


def test_pro_api_access_forbidden_only_team_has_it() -> None:
    session = _session_with(subscription=_active_sub(Plan.PRO))
    with pytest.raises(PlanLimitExceeded) as exc:
        assert_within_limit(session, _user("pro"), Resource.API_ACCESS)
    assert exc.value.code == 403


def test_team_api_access_allowed() -> None:
    session = _session_with(subscription=_active_sub(Plan.TEAM))
    assert_within_limit(session, _user("team"), Resource.API_ACCESS)


# --- unlimited (None) cap always passes ---


def test_team_topics_unlimited_passes() -> None:
    session = _session_with(usage=10_000, subscription=_active_sub(Plan.TEAM))
    assert_within_limit(session, _user("team"), Resource.TOPICS)


# --- AC8: expiry rollback ---


def test_expired_pro_rolls_back_to_free() -> None:
    session = _session_with(subscription=_expired_sub(Plan.PRO))
    assert effective_plan(session, _user("pro")) is Plan.FREE


def test_active_pro_stays_pro() -> None:
    session = _session_with(subscription=_active_sub(Plan.PRO))
    assert effective_plan(session, _user("pro")) is Plan.PRO


def test_expired_pro_blocks_channels_over_free_cap() -> None:
    # Expired Pro → effective Free; usage 5 (already over Free cap when adding one).
    session = MagicMock()
    session.scalar.return_value = 5
    scalars_result = MagicMock()
    scalars_result.one_or_none.return_value = _expired_sub(Plan.PRO)
    session.scalars.return_value = scalars_result
    with pytest.raises(PlanLimitExceeded) as exc:
        assert_within_limit(session, _user("pro"), Resource.CHANNELS)
    assert exc.value.code == 402
