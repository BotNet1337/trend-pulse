"""SQLAlchemy 2.0 declarative base + the seven domain models.

`EMBEDDING_DIM` is re-exported from `clusters` (single source of truth). All
models share one `Base.metadata`, so importing this package populates the full
schema used by Alembic autogenerate / migration `target_metadata`.
"""

from trendpulse.storage.models.alerts import Alert
from trendpulse.storage.models.base import Base
from trendpulse.storage.models.channels import Channel, SourceKind
from trendpulse.storage.models.clusters import EMBEDDING_DIM, Cluster
from trendpulse.storage.models.posts import Post
from trendpulse.storage.models.scores import Score
from trendpulse.storage.models.users import User
from trendpulse.storage.models.watchlists import Watchlist

__all__ = [
    "EMBEDDING_DIM",
    "Alert",
    "Base",
    "Channel",
    "Cluster",
    "Post",
    "Score",
    "SourceKind",
    "User",
    "Watchlist",
]
