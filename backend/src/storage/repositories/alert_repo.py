"""Tenant-scoped repository for `alerts` (ADR-002)."""

from storage.models.alerts import Alert
from storage.repositories.user_scoped import UserScopedRepository


class AlertRepository(UserScopedRepository[Alert]):
    model = Alert
