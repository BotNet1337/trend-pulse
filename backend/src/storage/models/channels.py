"""`channels` — GLOBAL source registry (ADR-001/002).

No `user_id`: a channel is read once for all tenants; users link to it via the
`watchlists` junction. `source_kind` keeps the schema multi-source from day one.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from storage.models.base import Base, utcnow

_HANDLE_MAX = 255


class SourceKind(enum.StrEnum):
    """Platform a channel belongs to (ADR-001). Mirrors `collector.base.SourceKind`.

    The `source_kind` column is `Enum(..., native_enum=False)` (VARCHAR(32), no DB
    CHECK constraint — see migration 0001), so adding a member needs NO migration.
    """

    TELEGRAM = "telegram"
    TWITTER = "twitter"  # TASK-031: second source (collector/twitter)


class Channel(Base):
    __tablename__ = "channels"
    __table_args__ = (
        UniqueConstraint("source_kind", "handle", name="uq_channels_source_kind_handle"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_kind: Mapped[SourceKind] = mapped_column(
        Enum(SourceKind, name="source_kind", native_enum=False, length=32),
        nullable=False,
        default=SourceKind.TELEGRAM,
    )
    handle: Mapped[str] = mapped_column(String(_HANDLE_MAX), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
