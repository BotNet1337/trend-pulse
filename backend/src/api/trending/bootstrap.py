"""Showcase-tenant bootstrap (TASK-039).

`ensure_showcase_tenant(session) -> int` — idempotent get-or-create of the system
showcase user (email = settings.showcase_user_email) + subscription to ALL catalog
packs via bulk-insert (bypassing the PACKS plan limit — showcase is a system tenant
that must have all packs; regular user limits are not weakened).

Design decisions:
- showcase = ordinary User row (is_active=True, is_verified=True, random hashed_password).
  Pipeline/scorer treat it as any other tenant — no special branches in the core.
- Password is hashed with PasswordHelper() (same argon2 hasher as UserManager uses)
  using a random secret that is NEVER stored or printed. This ensures that any login
  attempt triggers a proper argon2 verify (which will fail, since the random secret
  is discarded) rather than raising UnknownHashError — eliminating the 500/enumeration
  oracle (security invariant, AC4).
- Subscriptions use direct Watchlist bulk-insert (no limit check for this system tenant)
  with skip-on-conflict so idempotent repeated calls do not duplicate rows.
- Called from the `showcase-init` make target (explicit, no startup magic).
- Returns the showcase user's integer id.
"""

import logging
import secrets

from fastapi_users.password import PasswordHelper
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.packs.data import list_packs
from api.packs.service import _get_or_create_channel
from config import get_settings
from storage.models.users import User
from storage.models.watchlists import Watchlist

logger = logging.getLogger(__name__)


def _make_unguessable_hash() -> str:
    """Return a valid argon2 hash of a random secret for hashed_password.

    Uses the same PasswordHelper (argon2) as fastapi-users/UserManager so that
    login attempts against the showcase user trigger a proper (failing) argon2
    verify rather than raising UnknownHashError → 500. The random secret is
    discarded immediately and is never stored or printed (security invariant, AC4).
    """
    return PasswordHelper().hash(secrets.token_urlsafe(32))


def ensure_showcase_tenant(session: Session) -> int:
    """Get-or-create the system showcase user and subscribe it to all catalog packs.

    Idempotent: safe to call repeatedly. Second call returns the same user id and
    does not create duplicate subscriptions (skip-on-conflict). Returns the user's
    integer id so callers can use it for seeding test fixtures.

    Args:
        session: An open SQLAlchemy Session. The caller owns commit/rollback.

    Returns:
        The showcase user's integer id.
    """
    settings = get_settings()
    showcase_email = settings.showcase_user_email

    # --- 1. Get or create the showcase user row ---
    # Use User.__table__.c.email to work around a mypy false-positive: the email
    # column is declared in SQLAlchemyBaseUserTable (fastapi-users mixin) which
    # mypy cannot resolve to Mapped[str] when accessed as a class attribute
    # comparison — the table column reference always resolves correctly.
    existing = session.scalar(select(User).where(User.__table__.c.email == showcase_email))
    if existing is None:
        # Create with a random, unguessable hashed_password so no login is possible.
        # Password is never stored/printed (security invariant, AC4).
        user = User(
            email=showcase_email,
            hashed_password=_make_unguessable_hash(),
            is_active=True,
            is_verified=True,
        )
        session.add(user)
        session.flush()
        logger.info("showcase_tenant: created user id=%s", user.id)
    else:
        user = existing
        logger.debug("showcase_tenant: user id=%s already exists", user.id)

    user_id: int = user.id

    # --- 2. Subscribe to all catalog packs via direct Watchlist bulk-insert ---
    # We bypass assert_within_limit intentionally: the showcase tenant is a system
    # user that must track all packs to serve /trending for all topics. Regular user
    # limits are NOT weakened — this path is only taken here, not in packs/service.py.
    for pack in list_packs():
        for pack_channel in pack.channels:
            # Use savepoint so a conflict on one channel does not poison the batch.
            savepoint = session.begin_nested()
            try:
                channel = _get_or_create_channel(session, pack_channel.handle, pack_channel.kind)
                row = Watchlist(
                    user_id=user_id,
                    channel_id=channel.id,
                    topic=pack.topic,
                    threshold=float(pack.default_score_threshold),
                    min_channels=pack.default_min_channels,
                    lang=pack.default_notification_lang,
                    pack_slug=pack.slug,
                )
                session.add(row)
                session.flush()
                savepoint.commit()
            except IntegrityError:
                # Row already exists (idempotent re-run) or channel race — skip.
                savepoint.rollback()

    return user_id


__all__ = ["ensure_showcase_tenant"]
