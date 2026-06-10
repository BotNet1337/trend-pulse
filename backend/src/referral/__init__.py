"""Referral program module (TASK-046).

Public service interface — imported by billing/webhook.py and api/referral/.
All functions treat referral errors as non-fatal: callers MUST wrap in try/except
so that a referral failure never blocks registration or payment processing.
"""

from referral.service import (
    create_referral_reward_if_first_payment,
    generate_ref_code,
    get_or_create_ref_code,
    is_first_payment_for_referral,
    mark_reward_paid,
    resolve_referrer_id,
)

__all__ = [
    "create_referral_reward_if_first_payment",
    "generate_ref_code",
    "get_or_create_ref_code",
    "is_first_payment_for_referral",
    "mark_reward_paid",
    "resolve_referrer_id",
]
