"""User-database adapter + UserManager — fastapi-users config (no hand-rolled auth).

`get_user_db` binds the async SQLAlchemy session to the single `User`/`OAuthAccount`
models. `UserManager` subclasses `IntegerIDMixin` (integer PK) + `BaseUserManager`;
password hashing (argon2 via the default `PasswordHelper`), token issuing and the
register/verify/reset flows are all the library's — we only supply the secrets
(from settings) and a no-op-ish `on_after_register` log hook.
"""

import logging
from collections.abc import AsyncGenerator

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, IntegerIDMixin
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from storage.database import get_async_session
from storage.models.users import OAuthAccount, User

logger = logging.getLogger(__name__)


async def get_user_db(
    session: AsyncSession = Depends(get_async_session),
) -> AsyncGenerator[SQLAlchemyUserDatabase[User, int], None]:
    """Yield the SQLAlchemy user-db adapter bound to `User` + `OAuthAccount`."""
    yield SQLAlchemyUserDatabase(session, User, OAuthAccount)


class UserManager(IntegerIDMixin, BaseUserManager[User, int]):
    """fastapi-users manager for an integer-id `User`.

    The reset/verification token secrets reuse `jwt_secret` (single server secret,
    sourced from sensitive.env), set on the instance so a missing env still fails
    fast at construction. Hashing/token mechanics are inherited from the library —
    we do NOT implement them.
    """

    def __init__(self, user_db: SQLAlchemyUserDatabase[User, int]) -> None:
        super().__init__(user_db)
        secret = get_settings().jwt_secret
        self.reset_password_token_secret = secret
        self.verification_token_secret = secret

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        """Audit hook — log the new user id only (never email/password)."""
        logger.info("user registered: id=%s", user.id)


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase[User, int] = Depends(get_user_db),
) -> AsyncGenerator[UserManager, None]:
    """Yield a `UserManager` bound to the request-scoped user-db."""
    yield UserManager(user_db)
