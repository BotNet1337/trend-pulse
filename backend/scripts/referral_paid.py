"""Operator script: mark a referral_rewards row as paid (TASK-046).

Usage (via make referral-paid):
    make referral-paid ID=<reward_id>

Or directly:
    uv run python scripts/referral_paid.py --id <reward_id>

Validates:
  - Row with given ID exists in referral_rewards.
  - Row is currently in 'pending' status (refuses to re-mark already paid rows).

Prints the updated row on success; exits non-zero on error.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def main() -> None:
    """Entry point for the referral_paid script."""
    parser = argparse.ArgumentParser(
        description="Mark a referral_rewards row as paid.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run python scripts/referral_paid.py --id 1\n"
            "  make referral-paid ID=1\n"
        ),
    )
    parser.add_argument("--id", type=int, required=True, help="referral_rewards.id to mark paid")
    args = parser.parse_args()

    reward_id: int = args.id

    # Late import: avoid importing DB infra at module-level (script startup speed).
    from config import get_settings
    from storage.database import get_session

    get_settings()  # validates required env vars early (fail fast)

    with get_session() as session:
        _mark_paid(session, reward_id=reward_id)


def _mark_paid(session: Session, *, reward_id: int) -> None:
    """Fetch, validate, update the referral_rewards row and commit."""
    from sqlalchemy import select

    from referral.service import mark_reward_paid
    from storage.models.referral_rewards import REWARD_STATUS_PAID, ReferralReward

    row = session.scalar(select(ReferralReward).where(ReferralReward.id == reward_id))
    if row is None:
        print(f"ERROR: No referral_rewards row with id={reward_id}", file=sys.stderr)
        sys.exit(1)

    if row.status == REWARD_STATUS_PAID:
        print(
            f"ERROR: reward id={reward_id} is already marked paid "
            f"(paid_at={row.paid_at}). Nothing to do.",
            file=sys.stderr,
        )
        sys.exit(1)

    mark_reward_paid(session, reward_id=reward_id)
    session.commit()

    # Re-fetch to show final state.
    session.refresh(row)
    print(
        f"Updated referral_rewards id={reward_id}:\n"
        f"  referrer_id:      {row.referrer_id}\n"
        f"  referred_user_id: {row.referred_user_id}\n"
        f"  amount_usdt:      {row.amount_usdt}\n"
        f"  status:           {row.status}\n"
        f"  paid_at:          {row.paid_at}\n"
    )


if __name__ == "__main__":
    main()
