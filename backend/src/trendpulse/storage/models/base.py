"""Declarative base + shared column helpers for all ORM models.

Lives in its own module so individual model files can import `Base` without a
circular dependency on `models/__init__.py` (which aggregates every model).
"""

from datetime import UTC, datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base — single `metadata` for the whole schema."""


def utcnow() -> datetime:
    """Timezone-aware current UTC instant (never naive, never `datetime.utcnow`)."""
    return datetime.now(UTC)


class UserOwnedBase(Base):
    """Abstract base for tenant-owned tables: typed `id` PK + cascading `user_id` FK.

    Gives the repository layer a statically-typed `id`/`user_id` contract
    (no `Any`, no ignores) while enforcing DB-level `ON DELETE CASCADE`.
    """

    __abstract__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
