"""Referral program service layer (TASK-046).

All public functions operate on a synchronous SQLAlchemy `Session` (matching the
billing webhook's sync session pattern). Errors in this module MUST be caught by
callers — the referral path is always isolated from the main registration and
payment flows (Invariants: referral errors degrade silently with a log).

Business rules:
- ref_code: URL-safe, 8-char token generated via `secrets.token_urlsafe`; retried
  up to _MAX_CODE_RETRIES times on UNIQUE collision.
- referred_by: set at registration time via resolve_referrer_id(); write-once.
- Self-referral: blocked via `exclude_user_id` parameter on resolve_referrer_id().
- First-payment predicate: user has no prior processed BillingPayment AND no
  existing ReferralReward with their referred_user_id (double guard against replay).
- reward amount: sourced from settings.referral_reward_usdt (default 10.0).
"""

import logging
import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from observability.logging import log_event
from storage.models.users import User

logger = logging.getLogger(__name__)

# Code generation parameters — named, not magic literals (CONVENTIONS).
_CODE_BYTES = 6  # secrets.token_urlsafe(6) → 8-char base64url string
_MAX_CODE_RETRIES = 5

# Reward status constants (mirrors storage.models.referral_rewards).
_STATUS_PENDING = "pending"
_STATUS_PAID = "paid"

# BillingPayment status for a successfully processed (activated) payment.
_BILLING_STATUS_PROCESSED = "processed"


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------


def generate_ref_code() -> str:
    """Generate a URL-safe reference code (~8 chars).

    Uses secrets.token_urlsafe(6) which produces 8 URL-safe base64 characters
    (letters, digits, -, _) — short enough for a share link, no magic literals.
    """
    return secrets.token_urlsafe(_CODE_BYTES)


def get_or_create_ref_code(session: Session, *, user: User) -> str:
    """Return the user's existing ref_code or lazily generate one.

    On UNIQUE collision (extremely rare) retries up to _MAX_CODE_RETRIES times.
    Caller MUST flush/commit the session to persist the generated code.

    Each retry uses begin_nested() (SAVEPOINT) so a UNIQUE collision rolls back
    only the candidate assignment, not the caller's outer transaction.

    INVARIANT: never raises — callers in the API path wrap this in try/except.
    """
    u = user
    if u.ref_code is not None:
        return u.ref_code

    for attempt in range(_MAX_CODE_RETRIES):
        candidate = generate_ref_code()
        u.ref_code = candidate
        try:
            with session.begin_nested():
                session.flush()
            log_event("referral.code_generated", user_id=u.id, attempt=attempt)
            return candidate
        except IntegrityError:
            # UNIQUE collision: the savepoint was rolled back, outer tx is intact.
            logger.warning(
                "ref_code collision on attempt=%d for user_id=%s — retrying",
                attempt,
                u.id,
            )

    # Exhausted retries — extremely unlikely with a 48-bit random space.
    raise RuntimeError(
        f"Failed to generate a unique ref_code after {_MAX_CODE_RETRIES} attempts "
        f"for user_id={u.id}"
    )


# ---------------------------------------------------------------------------
# Referrer resolution
# ---------------------------------------------------------------------------


def resolve_referrer_id(
    session: Session,
    *,
    ref_code: str,
    exclude_user_id: int | None = None,
) -> int | None:
    """Look up a referrer by ref_code; return their id or None.

    Returns None when:
    - No user has that ref_code (unknown/invalid code).
    - The resolved user's id matches exclude_user_id (self-referral guard).

    INVARIANT: always returns None on any error — never raises (caller must not
    need to guard further; the contract here is 'None == no referral').
    """
    from storage.models.users import User

    try:
        # .unique() required: User has lazy="joined" on oauth_accounts collection,
        # which causes a joined-load result that requires explicit uniquing.
        referrer = (
            session.scalars(select(User).where(User.ref_code == ref_code)).unique().one_or_none()
        )
        if referrer is None:
            return None
        if exclude_user_id is not None and referrer.id == exclude_user_id:
            log_event("referral.self_referral_blocked", user_id=exclude_user_id)
            return None
        return referrer.id
    except Exception:
        logger.exception("referral.resolve_referrer_id failed for ref_code (hidden)")
        return None


# ---------------------------------------------------------------------------
# First-payment predicate
# ---------------------------------------------------------------------------


def _referral_reward_exists(session: Session, *, user_id: int) -> bool:
    """Return True if a ReferralReward already exists for this referred_user_id.

    Uses limit(1).first() (EXISTS-style) to avoid MultipleResultsFound if somehow
    duplicate rows exist, and to short-circuit after the first match.
    """
    from storage.models.referral_rewards import ReferralReward

    row = session.scalars(
        select(ReferralReward).where(ReferralReward.referred_user_id == user_id).limit(1)
    ).first()
    return row is not None


def is_first_payment_for_referral(session: Session, *, user_id: int) -> bool:
    """True iff this is the user's first processed payment AND no reward exists yet.

    'First processed payment' = no BillingPayment with status='processed' for
    this user_id (the current payment being processed is NOT yet flushed as
    'processed' when this runs — caller responsibility).
    'No reward' = UNIQUE referred_user_id guard (double protection vs IPN replay).

    Uses limit(1).first() for the processed-payment check so that multiple prior
    processed rows (e.g., renewals) do not raise MultipleResultsFound.
    """
    from storage.models.subscriptions import BillingPayment

    prior_payment = session.scalars(
        select(BillingPayment)
        .where(
            BillingPayment.user_id == user_id,
            BillingPayment.status == _BILLING_STATUS_PROCESSED,
        )
        .limit(1)
    ).first()
    if prior_payment is not None:
        return False

    return not _referral_reward_exists(session, user_id=user_id)


# ---------------------------------------------------------------------------
# Reward creation
# ---------------------------------------------------------------------------


def create_referral_reward_if_first_payment(
    session: Session,
    *,
    user_id: int,
    payment_id: int,
) -> None:
    """Create a ReferralReward if this is the referred user's first payment.

    Steps:
    1. Load the user; if no referred_by, nothing to do.
    2. Call is_first_payment_for_referral — skip if not eligible.
    3. INSERT referral_rewards row inside a SAVEPOINT (begin_nested).
       - IntegrityError (UNIQUE race) rolls back only the savepoint; outer tx intact.
       - Any other exception rolls back the savepoint; outer tx intact.
    4. log_event on success.

    CRITICAL: ALL reward logic runs inside session.begin_nested() so that ANY failure
    (IntegrityError, OperationalError, RuntimeError, …) rolls back only the savepoint
    and never contaminates the caller's outer transaction (billing/webhook.py session).
    autoflush=False is preserved — no implicit flush escapes the savepoint boundary.

    INVARIANT: all errors are caught and logged — never re-raises.
    The caller (billing/webhook.py) wraps this in try/except for belt-and-suspenders.
    """
    from config import get_settings
    from storage.models.referral_rewards import ReferralReward
    from storage.models.users import User

    try:
        user = session.get(User, user_id)
        if user is None or user.referred_by is None:
            return

        if not is_first_payment_for_referral(session, user_id=user_id):
            return

        amount = get_settings().referral_reward_usdt
        reward = ReferralReward(
            referrer_id=user.referred_by,
            referred_user_id=user_id,
            payment_id=payment_id,
            amount_usdt=amount,
            status=_STATUS_PENDING,
        )
        # Use a SAVEPOINT so any failure (UNIQUE race, transient DB error, …) rolls
        # back ONLY the reward INSERT and leaves the outer IPN transaction intact.
        try:
            with session.begin_nested():
                session.add(reward)
                session.flush()
        except IntegrityError:
            # UNIQUE constraint on referred_user_id — concurrent IPN race, already
            # handled by the pre-check but guarded here as a belt-and-suspenders.
            # The savepoint was automatically rolled back; outer tx is clean.
            logger.warning(
                "referral.reward_duplicate_skipped user_id=%s payment_id=%s",
                user_id,
                payment_id,
            )
            return
        except Exception:
            # Any other DB/runtime error during the INSERT — savepoint rolled back.
            logger.exception(
                "referral.reward_insert_failed user_id=%s payment_id=%s",
                user_id,
                payment_id,
            )
            return

        log_event(
            "referral_reward_created",
            referrer_id=user.referred_by,
            referred_user_id=user_id,
            amount_usdt=amount,
            payment_id=payment_id,
        )

    except Exception:
        logger.exception(
            "referral.create_reward failed for user_id=%s payment_id=%s",
            user_id,
            payment_id,
        )


# ---------------------------------------------------------------------------
# Operator: mark paid
# ---------------------------------------------------------------------------


def mark_reward_paid(session: Session, *, reward_id: int) -> None:
    """Set status='paid' and paid_at=now() on the given reward row.

    Used by the operator script (make referral-paid ID=...).
    Raises ValueError if the reward does not exist.
    """
    from storage.models.base import utcnow
    from storage.models.referral_rewards import ReferralReward

    reward = session.get(ReferralReward, reward_id)
    if reward is None:
        raise ValueError(f"No referral_rewards row with id={reward_id}")
    reward.status = _STATUS_PAID
    reward.paid_at = utcnow()
    session.flush()
    log_event("referral_reward_paid", reward_id=reward_id, referrer_id=reward.referrer_id)
