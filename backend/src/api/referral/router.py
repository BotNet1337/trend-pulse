"""GET /referral/me — referral code, share link, and rewards list (TASK-046).

Endpoint behaviour:
- Requires authenticated user (current_user dependency).
- Lazily generates ref_code on first call (get_or_create_ref_code).
- Builds the registration share link using settings.frontend_base_url
  (the SPA base URL — user navigates to /auth/sign-up?ref=CODE).
- Returns only THIS user's earned rewards (tenant-scoped).

Security: referral code exposure is intentional (it is a share code); it is
NOT a secret. The endpoint is auth-gated so a user can only view their own code.
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import current_user
from api.referral.schemas import ReferralMeRead, ReferralRewardRead
from api.watchlist.deps import get_db_session
from config import get_settings
from referral.service import get_or_create_ref_code
from storage.models.referral_rewards import ReferralReward
from storage.models.users import User

logger = logging.getLogger(__name__)

# Path constant (CONVENTIONS: no magic literals).
_SIGN_UP_PATH = "/auth/sign-up"
_REF_QUERY_PARAM = "ref"

router = APIRouter(prefix="/referral", tags=["referral"])


@router.get("/me", response_model=ReferralMeRead)
def get_referral_me(
    user: User = Depends(current_user),
    session: Session = Depends(get_db_session),
) -> ReferralMeRead:
    """Return the authenticated user's referral code, share link, and earned rewards.

    The ref_code is generated lazily on first call and cached on the user row.
    Only rewards where referrer_id == current_user.id are returned.
    """
    # Reload user from the sync session for accurate in-transaction state.
    from sqlalchemy import select as sa_select

    db_user = session.scalars(sa_select(User).where(User.id == user.id)).unique().one()

    # Lazily generate the ref_code if not yet created.
    ref_code = get_or_create_ref_code(session, user=db_user)
    session.commit()

    # Build share link using the frontend base URL.
    settings = get_settings()
    base = settings.frontend_base_url.rstrip("/")
    referral_link = f"{base}{_SIGN_UP_PATH}?{_REF_QUERY_PARAM}={ref_code}"

    # Fetch this user's earned rewards (only their own — tenant-scoped).
    reward_rows = session.scalars(
        select(ReferralReward).where(ReferralReward.referrer_id == db_user.id)
    ).all()

    rewards = [
        ReferralRewardRead(
            id=r.id,
            referrer_id=r.referrer_id,
            referred_user_id=r.referred_user_id,
            payment_id=r.payment_id,
            amount_usdt=r.amount_usdt,
            status=r.status,
            created_at=r.created_at,
            paid_at=r.paid_at,
        )
        for r in reward_rows
    ]

    return ReferralMeRead(
        ref_code=ref_code,
        referral_link=referral_link,
        rewards=rewards,
    )
