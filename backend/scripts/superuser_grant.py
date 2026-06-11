"""Operator script: grant superuser privileges to a user by email (TASK-051).

Usage (via make superuser-grant):
    make superuser-grant EMAIL=<email>

Or directly:
    uv run python scripts/superuser_grant.py --email <email>

Behaviour:
  - Idempotent: if the user is already a superuser, prints a confirmation and exits 0.
  - Unknown email → human-readable error message, exits non-zero (no stack trace).
  - Does not reveal other user data in error output (no PII leakage).
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def main() -> None:
    """Entry point for the superuser_grant script."""
    parser = argparse.ArgumentParser(
        description="Grant superuser privileges to a user by email.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run python scripts/superuser_grant.py --email admin@example.com\n"
            "  make superuser-grant EMAIL=admin@example.com\n"
        ),
    )
    parser.add_argument(
        "--email",
        type=str,
        required=True,
        help="Email address of the user to promote to superuser",
    )
    args = parser.parse_args()

    email: str = args.email.strip()

    # Late import: avoid importing DB infra at module-level (script startup speed).
    from config import get_settings
    from storage.database import get_session

    get_settings()  # validates required env vars early (fail fast)

    with get_session() as session:
        _grant_superuser(session, email=email)


def _grant_superuser(session: Session, *, email: str) -> None:
    """Fetch the user, validate, set is_superuser=True and commit."""
    from sqlalchemy import select, update

    from storage.models.users import User

    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        print(
            f"ERROR: No user found with email={email!r}. Check the email address and try again.",
            file=sys.stderr,
        )
        sys.exit(1)

    if user.is_superuser:
        print(f"User {email!r} (id={user.id}) is already a superuser. Nothing to do.")
        return

    session.execute(update(User).where(User.id == user.id).values(is_superuser=True))
    session.commit()

    print(f"Granted superuser to {email!r} (id={user.id}).\n  is_superuser: True\n")


if __name__ == "__main__":
    main()
