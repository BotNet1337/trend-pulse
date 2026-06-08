"""Tenant-scoped repository for `clusters` (ADR-002)."""

from storage.models.clusters import Cluster
from storage.repositories.user_scoped import UserScopedRepository


class ClusterRepository(UserScopedRepository[Cluster]):
    model = Cluster
