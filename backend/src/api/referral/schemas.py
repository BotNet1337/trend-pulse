"""Pydantic schemas for the referral API (TASK-046).

`extra="forbid"` follows the project pattern (api/account/delivery_config.py) —
unexpected fields in responses are never silently returned to clients.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ReferralRewardRead(BaseModel):
    """One reward row as returned by GET /referral/me."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    referrer_id: int
    referred_user_id: int | None
    payment_id: int | None
    amount_usdt: float
    status: str
    created_at: datetime
    paid_at: datetime | None


class ReferralMeRead(BaseModel):
    """Response schema for GET /referral/me.

    ref_code: the authenticated user's unique share code (generated lazily).
    referral_link: full registration URL pre-filled with the ref code.
    rewards: list of reward rows earned by this user (pending and paid).
    """

    model_config = ConfigDict(extra="forbid")

    ref_code: str
    referral_link: str
    rewards: list[ReferralRewardRead]
