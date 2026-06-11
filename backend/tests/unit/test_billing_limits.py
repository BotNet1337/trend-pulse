"""AC7/AC8 — plan-limit enforcement (DB-free; mocked usage + subscription).

Covers: channel cap per plan (Free 0 / Pro 100 / Team 500, TASK-049), boolean
feature gating (webhook_delivery / api_access → 403), unlimited (`None`) always
passes, and the expiry rollback (an expired Pro subscription → effective Free).

TASK-038 additions: _channel_usage excludes pack rows (pack_slug IS NOT NULL),
_packs_usage counts DISTINCT pack_slug, assert_within_limit(PACKS) raises at Free cap.

TASK-049: Free CHANNELS cap changed 5→0 (Free = воронка, паки + задержка).
         PACKS cap for Free remains 1 — pack subscribe still works.

TASK-048: expiry rollback gets a 72h grace window (GRACE_PERIOD_SECONDS) —
         «expired → Free» honestly becomes «expired + grace elapsed → Free».

The single entry under test is `billing.assert_within_limit`; `effective_plan`
resolves the rollback. The session is mocked so these stay unit tests.
"""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from billing.constants import GRACE_PERIOD_SECONDS
from billing.limits import (
    PlanLimitExceeded,
    _channel_usage,
    _packs_usage,
    assert_within_limit,
    effective_plan,
)
from billing.plans import Plan, Resource
from storage.models.base import utcnow
from storage.models.subscriptions import Subscription
from storage.models.users import User

_ONE_HOUR = timedelta(hours=1)
_GRACE = timedelta(seconds=GRACE_PERIOD_SECONDS)


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


def _expired_sub(plan: Plan, *, expired_for: timedelta = _GRACE + _ONE_HOUR) -> Subscription:
    """A subscription whose expiry passed `expired_for` ago (default: beyond grace).

    TASK-048: the default is PAST the 72h grace window so the legacy
    «expired → Free» tests keep their meaning («expired + grace → Free»).
    """
    return Subscription(user_id=1, plan=plan.value, expires_at=utcnow() - expired_for)


# --- AC7: channel cap per plan ---

# TASK-049: Free CHANNELS=0 (Free = воронка). The very first own channel → 402.


def test_free_channels_first_own_raises_402() -> None:
    """AC2 (TASK-049): Free plan CHANNELS=0 → even usage=0 triggers 402 on create."""
    session = _session_with(usage=0)  # zero existing own channels
    with pytest.raises(PlanLimitExceeded) as exc:
        assert_within_limit(session, _user("free"), Resource.CHANNELS)
    assert exc.value.code == 402


def test_free_channels_at_cap_raises_402() -> None:
    """AC2 (TASK-049): Free cap is 0 — any usage (even 1) still raises on further create."""
    session = _session_with(usage=1)  # already has 1 (grandfathered) — next is still blocked
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


# --- AC8: expiry rollback (+ 72h grace, TASK-048 AC4) ---


def test_expired_pro_rolls_back_to_free() -> None:
    """AC8 + grace TASK-048: expired beyond the 72h grace window → Free."""
    session = _session_with(subscription=_expired_sub(Plan.PRO))
    assert effective_plan(session, _user("pro")) is Plan.FREE


def test_active_pro_stays_pro() -> None:
    session = _session_with(subscription=_active_sub(Plan.PRO))
    assert effective_plan(session, _user("pro")) is Plan.PRO


def test_expired_1h_ago_within_grace_stays_pro() -> None:
    """AC4 (TASK-048): expiry 1h ago is inside the 72h grace → plan retained."""
    session = _session_with(subscription=_expired_sub(Plan.PRO, expired_for=_ONE_HOUR))
    assert effective_plan(session, _user("pro")) is Plan.PRO


def test_expired_71h_ago_within_grace_stays_pro() -> None:
    """AC4 (TASK-048): 71h after expiry is still inside the 72h grace."""
    session = _session_with(subscription=_expired_sub(Plan.PRO, expired_for=timedelta(hours=71)))
    assert effective_plan(session, _user("pro")) is Plan.PRO


def test_expired_73h_ago_beyond_grace_is_free() -> None:
    """AC4 (TASK-048): 73h after expiry the grace is over → Free."""
    session = _session_with(subscription=_expired_sub(Plan.PRO, expired_for=timedelta(hours=73)))
    assert effective_plan(session, _user("pro")) is Plan.FREE


def test_expired_team_within_grace_stays_team() -> None:
    """AC4 (TASK-048): grace applies to every paid plan, not just Pro."""
    session = _session_with(subscription=_expired_sub(Plan.TEAM, expired_for=_ONE_HOUR))
    assert effective_plan(session, _user("team")) is Plan.TEAM


def test_no_subscription_row_is_free_no_grace() -> None:
    """TASK-048: a missing subscription row never gets grace — Free as before."""
    session = _session_with(subscription=None)
    assert effective_plan(session, _user("pro")) is Plan.FREE


def test_null_expiry_is_free_no_grace() -> None:
    """TASK-048: `expires_at IS NULL` (no paid period) stays Free — no grace."""
    session = _session_with(subscription=Subscription(user_id=1, plan="pro", expires_at=None))
    assert effective_plan(session, _user("pro")) is Plan.FREE


def test_expired_pro_blocks_channels_over_free_cap() -> None:
    # TASK-049: Expired Pro → effective Free; Free CHANNELS=0 → any create blocked (usage=0).
    session = MagicMock()
    session.scalar.return_value = 0
    scalars_result = MagicMock()
    scalars_result.one_or_none.return_value = _expired_sub(Plan.PRO)
    session.scalars.return_value = scalars_result
    with pytest.raises(PlanLimitExceeded) as exc:
        assert_within_limit(session, _user("pro"), Resource.CHANNELS)
    assert exc.value.code == 402


# ─── TASK-038: PACKS resource + _channel_usage/_packs_usage helpers ───────────


def test_channel_usage_returns_scalar_from_session() -> None:
    """_channel_usage delegates to session.scalar() — result plumbed through correctly.

    The SQL filter (pack_slug IS NULL) is verified by the integration test
    test_pack_rows_do_not_consume_channel_limit (AC3). Here we confirm the helper
    returns the integer the DB would return.
    """
    session = MagicMock()
    session.scalar.return_value = 3
    assert _channel_usage(session, user_id=1) == 3


def test_channel_usage_treats_none_scalar_as_zero() -> None:
    """_channel_usage coerces None (no rows) to 0."""
    session = MagicMock()
    session.scalar.return_value = None
    assert _channel_usage(session, user_id=1) == 0


def test_packs_usage_returns_distinct_count_from_session() -> None:
    """_packs_usage delegates to session.scalar() — distinct pack_slug count plumbed through.

    The SQL filter (pack_slug IS NOT NULL, COUNT DISTINCT) is verified by integration
    test test_second_pack_returns_402_for_free_user (AC3). Here we confirm the helper
    returns the session scalar value.
    """
    session = MagicMock()
    session.scalar.return_value = 2
    assert _packs_usage(session, user_id=1) == 2


def test_packs_usage_treats_none_scalar_as_zero() -> None:
    """_packs_usage coerces None (no pack rows) to 0."""
    session = MagicMock()
    session.scalar.return_value = None
    assert _packs_usage(session, user_id=1) == 0


def test_free_packs_at_cap_raises_402() -> None:
    """assert_within_limit(PACKS) raises 402 when Free user is at cap (1 pack)."""
    # Free plan PACKS cap = 1; usage=1 → adding one more would breach it.
    session = _session_with(usage=1)
    with pytest.raises(PlanLimitExceeded) as exc:
        assert_within_limit(session, _user("free"), Resource.PACKS)
    assert exc.value.code == 402


def test_free_packs_under_cap_passes() -> None:
    """assert_within_limit(PACKS) passes when Free user has 0 packs (cap=1)."""
    session = _session_with(usage=0)
    assert_within_limit(session, _user("free"), Resource.PACKS)  # should not raise


def test_free_packs_subscribe_ok_while_channels_zero() -> None:
    """AC2 (TASK-049): CHANNELS=0 does NOT block pack subscribe (PACKS cap unchanged at 1).

    Free is funnel: own channels blocked but curated packs still work.
    Verifies that Free CHANNELS=0 (TASK-049) and Free PACKS=1 are independent resources.
    """
    # CHANNELS are at cap (0 allowed) — but we test PACKS here, not CHANNELS.
    session_packs = _session_with(usage=0)
    # Must not raise: Free user with 0 packs is within PACKS cap=1.
    assert_within_limit(session_packs, _user("free"), Resource.PACKS)  # pack subscribe OK


def test_pro_packs_at_cap_raises_402() -> None:
    """assert_within_limit(PACKS) raises 402 when Pro user is at cap (5 packs)."""
    session = _session_with(usage=5, subscription=_active_sub(Plan.PRO))
    with pytest.raises(PlanLimitExceeded) as exc:
        assert_within_limit(session, _user("pro"), Resource.PACKS)
    assert exc.value.code == 402


def test_pro_packs_under_cap_passes() -> None:
    """assert_within_limit(PACKS) passes when Pro user has 3 packs (cap=5)."""
    session = _session_with(usage=3, subscription=_active_sub(Plan.PRO))
    assert_within_limit(session, _user("pro"), Resource.PACKS)  # should not raise
