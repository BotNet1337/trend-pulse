"""Tenant-scoped repository for `watchlists` (ADR-002)."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from storage.models.watchlists import Watchlist
from storage.repositories.user_scoped import UserScopedRepository


class WatchlistRepository(UserScopedRepository[Watchlist]):
    model = Watchlist

    def list_for_channel(
        self, session: Session, *, user_id: int, channel_id: int
    ) -> Sequence[Watchlist]:
        stmt = (
            select(Watchlist)
            .where(Watchlist.user_id == user_id)
            .where(Watchlist.channel_id == channel_id)
        )
        return session.scalars(stmt).all()
