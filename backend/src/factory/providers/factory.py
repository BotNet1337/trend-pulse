"""Env-based selection of the SmsProvider / TelegramRegistrar impls (TASK-133).

`ACCOUNT_FACTORY_PROVIDER` chooses the impl; default `fake` keeps CI/this env
network-free. The real SMSPVA path requires `SMSPVA_API_KEY` (fail fast — never a
silent fallback to the fake). The real Telethon registrar additionally requires the
telegram api creds; absent them, the fake registrar is used (so a provider can be
exercised against SMSPVA without a real registration path configured).
"""

from __future__ import annotations

from config import Settings
from factory.constants import ACCOUNT_FACTORY_PROVIDER_SMSPVA
from factory.errors import FactoryError
from factory.providers.base import SmsProvider
from factory.providers.fake import FakeSmsProvider
from factory.providers.smspva import build_smspva_provider
from factory.registrar.base import TelegramRegistrar
from factory.registrar.fake import FakeRegistrar
from factory.registrar.telethon import TelethonRegistrar


def get_sms_provider(settings: Settings) -> SmsProvider:
    """Return the SMS provider selected by `settings.account_factory_provider`.

    `smspva` requires a non-empty `smspva_api_key` — an empty key raises
    `FactoryError` rather than silently degrading to the fake (which would mask a
    misconfiguration). Any other value (including the default `fake`) → `FakeSmsProvider`.
    """
    if settings.account_factory_provider == ACCOUNT_FACTORY_PROVIDER_SMSPVA:
        if not settings.smspva_api_key:
            raise FactoryError("ACCOUNT_FACTORY_PROVIDER=smspva but SMSPVA_API_KEY is empty")
        return build_smspva_provider(api_key=settings.smspva_api_key)
    return FakeSmsProvider()


def get_registrar(settings: Settings) -> TelegramRegistrar:
    """Return the Telegram registrar for the selected provider.

    The real `TelethonRegistrar` is used ONLY when the SMSPVA provider is selected AND
    the telegram api creds (`telegram_api_id`/`telegram_api_hash`) are present;
    otherwise the deterministic `FakeRegistrar` is returned.
    """
    if (
        settings.account_factory_provider == ACCOUNT_FACTORY_PROVIDER_SMSPVA
        and settings.telegram_api_id is not None
        and settings.telegram_api_hash is not None
    ):
        return TelethonRegistrar(
            api_id=settings.telegram_api_id, api_hash=settings.telegram_api_hash
        )
    return FakeRegistrar()
