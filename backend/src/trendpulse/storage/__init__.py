"""Public storage API: ORM base/models, repositories, session + Redis factories."""

from trendpulse.storage.database import SessionLocal, engine, get_session
from trendpulse.storage.models import (
    EMBEDDING_DIM,
    Alert,
    Base,
    Channel,
    Cluster,
    Post,
    Score,
    SourceKind,
    User,
    Watchlist,
)
from trendpulse.storage.redis_client import get_redis_client
from trendpulse.storage.repositories import (
    AlertRepository,
    ChannelRepository,
    ClusterRepository,
    Repository,
    UserScopedRepository,
    WatchlistRepository,
)

__all__ = [
    "EMBEDDING_DIM",
    "Alert",
    "AlertRepository",
    "Base",
    "Channel",
    "ChannelRepository",
    "Cluster",
    "ClusterRepository",
    "Post",
    "Repository",
    "Score",
    "SessionLocal",
    "SourceKind",
    "User",
    "UserScopedRepository",
    "Watchlist",
    "WatchlistRepository",
    "engine",
    "get_redis_client",
    "get_session",
]
