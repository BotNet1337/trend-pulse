"""SQLAlchemy 2.0 declarative base + the nine domain models.

`EMBEDDING_DIM` is re-exported from `clusters` (single source of truth). All
models share one `Base.metadata`, so importing this package populates the full
schema used by Alembic autogenerate / migration `target_metadata`.
"""

from storage.models.alert_feedback import AlertFeedback
from storage.models.alerts import Alert
from storage.models.api_keys import ApiKey
from storage.models.base import Base
from storage.models.business_metrics import BusinessMetricsDaily
from storage.models.channels import Channel, SourceKind
from storage.models.clusters import EMBEDDING_DIM, Cluster
from storage.models.posts import Post
from storage.models.referral_rewards import ReferralReward
from storage.models.scores import Score
from storage.models.showcase_cases import ShowcaseCase
from storage.models.showcase_posts import ShowcasePost
from storage.models.subscriptions import BillingPayment, Subscription
from storage.models.users import OAuthAccount, User
from storage.models.watchlists import Watchlist

__all__ = [
    "EMBEDDING_DIM",
    "Alert",
    "AlertFeedback",
    "ApiKey",
    "Base",
    "BillingPayment",
    "BusinessMetricsDaily",
    "Channel",
    "Cluster",
    "OAuthAccount",
    "Post",
    "ReferralReward",
    "Score",
    "ShowcaseCase",
    "ShowcasePost",
    "SourceKind",
    "Subscription",
    "User",
    "Watchlist",
]
