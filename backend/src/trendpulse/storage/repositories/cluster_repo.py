"""Tenant-scoped repository for `clusters` (ADR-002)."""

from trendpulse.storage.models.clusters import Cluster
from trendpulse.storage.repositories.user_scoped import UserScopedRepository


class ClusterRepository(UserScopedRepository[Cluster]):
    model = Cluster
