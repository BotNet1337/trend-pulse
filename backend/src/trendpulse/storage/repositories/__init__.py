"""Repository layer: global (`channels`) + tenant-scoped (ADR-002) data access."""

from trendpulse.storage.repositories.alert_repo import AlertRepository
from trendpulse.storage.repositories.base import Repository
from trendpulse.storage.repositories.channel_repo import ChannelRepository
from trendpulse.storage.repositories.cluster_repo import ClusterRepository
from trendpulse.storage.repositories.user_scoped import UserScopedRepository
from trendpulse.storage.repositories.watchlist_repo import WatchlistRepository

__all__ = [
    "AlertRepository",
    "ChannelRepository",
    "ClusterRepository",
    "Repository",
    "UserScopedRepository",
    "WatchlistRepository",
]
