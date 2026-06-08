"""`users` — tenant root. Account deletion cascades to all user-owned tables."""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from trendpulse.storage.models.base import Base, utcnow

_EMAIL_MAX = 320  # RFC 5321 max email length.


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(_EMAIL_MAX), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
