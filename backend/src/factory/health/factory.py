"""Env-based selection of the HealthProbe impl (TASK-141).

The real `TelethonHealthProbe` (an honest read of a public channel over the account's
session+proxy) is used ONLY when ALL of the following hold (mirrors `get_registrar`'s
gating, plus the probe channel):
  * a REAL SMS provider is selected (`account_factory_provider == smspva`),
  * the telegram api creds are present (`telegram_api_id`/`telegram_api_hash`),
  * a non-empty probe channel is configured (`account_factory_health_probe_channel`).
Otherwise the deterministic `FakeHealthProbe` is returned, so the fake/offline path is
a deterministic pass and a misconfigured (unset) channel can NOT blackhole promotion.
"""

from __future__ import annotations

from config import Settings
from factory.constants import ACCOUNT_FACTORY_PROVIDER_SMSPVA, FACTORY_HEALTH_READ_LIMIT
from factory.health.base import HealthProbe
from factory.health.fake import FakeHealthProbe
from factory.health.telethon import TelethonHealthProbe


def get_health_probe(settings: Settings) -> HealthProbe:
    """Return the pre-promote health probe selected by the factory settings.

    Real `TelethonHealthProbe` iff a real provider + telegram creds + a probe channel
    are all configured; else `FakeHealthProbe()` (deterministic, offline).
    """
    channel = settings.account_factory_health_probe_channel.strip()
    if (
        settings.account_factory_provider == ACCOUNT_FACTORY_PROVIDER_SMSPVA
        and settings.telegram_api_id is not None
        and settings.telegram_api_hash is not None
        and channel
    ):
        return TelethonHealthProbe(
            api_id=settings.telegram_api_id,
            api_hash=settings.telegram_api_hash,
            channel=channel,
            read_limit=FACTORY_HEALTH_READ_LIMIT,
        )
    return FakeHealthProbe()
