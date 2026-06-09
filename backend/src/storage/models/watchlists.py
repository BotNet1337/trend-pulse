"""`watchlists` — user↔channel↔topic junction carrying alert config (overview §3)."""

from sqlalchemy import Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from storage.models.base import UserOwnedBase

_TOPIC_MAX = 255
_LANG_MAX = 16
_DEFAULT_THRESHOLD = 0.0
_DEFAULT_MIN_CHANNELS = 1
_DEFAULT_LANG = "en"
# Pack slug column width — named constant, mirrors migration 0011 (TASK-038).
_PACK_SLUG_MAX = 64


class Watchlist(UserOwnedBase):
    __tablename__ = "watchlists"
    __table_args__ = (
        UniqueConstraint("user_id", "channel_id", "topic", name="uq_watchlists_user_channel_topic"),
        Index("ix_watchlists_user_id", "user_id"),
        Index("ix_watchlists_user_pack", "user_id", "pack_slug"),
    )

    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), nullable=False)
    topic: Mapped[str] = mapped_column(String(_TOPIC_MAX), nullable=False)
    # Alert config lives per watchlist (topic/list level), not per account.
    threshold: Mapped[float] = mapped_column(Float, nullable=False, default=_DEFAULT_THRESHOLD)
    min_channels: Mapped[int] = mapped_column(
        Integer, nullable=False, default=_DEFAULT_MIN_CHANNELS
    )
    lang: Mapped[str] = mapped_column(String(_LANG_MAX), nullable=False, default=_DEFAULT_LANG)
    # Pack marker (TASK-038): NULL = manually created; non-NULL = belongs to a curated pack.
    # Used by billing/_channel_usage to exclude pack rows from the CHANNELS counter so
    # pack channels do not consume the user's manual channel cap.
    pack_slug: Mapped[str | None] = mapped_column(
        String(_PACK_SLUG_MAX), nullable=True, default=None
    )
