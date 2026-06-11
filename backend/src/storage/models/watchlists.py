"""`watchlists` — user↔channel↔topic junction carrying alert config (overview §3)."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from storage.models.base import UserOwnedBase, utcnow

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
    # Adaptive threshold floor (TASK-043): the user-intent anchor for the adapt loop.
    # NULL = not yet snapshotted (first adapt tick will snapshot current threshold).
    # Non-NULL = the threshold value the user last set manually; adaptation never goes
    # below this value and never above floor + threshold_adapt_range (ceiling).
    # Updated by the PATCH threshold path in api/watchlist/service.py so manual
    # user changes re-anchor the floor to the new intent value.
    threshold_floor: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    # Creation timestamp (TASK-050): used by analytics aggregate to count packs_attached
    # per day. Added in migration 0018; server_default=now() so existing rows get the
    # migration timestamp (acceptable approximation — documented in task Discussion).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=text("now()"),
    )
