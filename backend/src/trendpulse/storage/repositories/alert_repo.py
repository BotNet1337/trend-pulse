"""Tenant-scoped repository for `alerts` (ADR-002)."""

from trendpulse.storage.models.alerts import Alert
from trendpulse.storage.repositories.user_scoped import UserScopedRepository


class AlertRepository(UserScopedRepository[Alert]):
    model = Alert
