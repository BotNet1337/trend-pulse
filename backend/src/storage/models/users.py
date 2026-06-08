"""`users` — tenant root and the fastapi-users user table.

This is the SINGLE `User` model for the whole app. It is the tenant root (every
user-owned table FKs `user_id -> users.id ON DELETE CASCADE`, task-002) AND the
fastapi-users user table: it mixes in `SQLAlchemyBaseUserTable[int]`, which adds
`email` (unique), `hashed_password`, `is_active`, `is_superuser`, `is_verified`.

The id stays an **integer** PK (`FastAPIUsers[User, int]`) — switching to UUID
would break every existing `user_id` FK. The mixin is a plain `Generic[ID]`
(not a `DeclarativeBase`), so it composes with our `Base` without a metaclass
clash. `email` is declared by the mixin only (no double definition).
"""

from datetime import datetime

from fastapi_users_db_sqlalchemy import (
    SQLAlchemyBaseOAuthAccountTable,
    SQLAlchemyBaseUserTable,
)
from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from storage.models.base import Base, utcnow


class OAuthAccount(SQLAlchemyBaseOAuthAccountTable[int], Base):
    """Linked third-party (Google) identity for a user — fastapi-users OAuth table.

    Integer PK + integer `user_id` FK into `users` with `ON DELETE CASCADE`,
    consistent with the rest of the schema (account deletion removes linked
    OAuth accounts). The base mixin supplies `oauth_name`, `access_token`,
    `expires_at`, `refresh_token`, `account_id`, `account_email`.
    """

    __tablename__ = "oauth_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )


class User(SQLAlchemyBaseUserTable[int], Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    # `lazy="joined"` is required by fastapi-users so the OAuth router can read a
    # user's linked accounts in one query; `passive_deletes` defers row removal to
    # the DB-level CASCADE above (no per-row ORM delete).
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(
        OAuthAccount, lazy="joined", passive_deletes=True
    )
