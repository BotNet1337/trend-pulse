"""Env-based selection of the SmsProvider / TelegramRegistrar impls (TASK-133).

`ACCOUNT_FACTORY_PROVIDER` chooses the impl; default `fake` keeps CI/this env
network-free. The real SMSPVA path requires `SMSPVA_API_KEY` (fail fast — never a
silent fallback to the fake). The real Telethon registrar additionally requires the
telegram api creds; absent them, the fake registrar is used (so a provider can be
exercised against SMSPVA without a real registration path configured).
"""

from __future__ import annotations

from config import Settings
from factory.constants import (
    ACCOUNT_FACTORY_PROVIDER_SMSPVA,
    ACCOUNT_FACTORY_PROVIDER_SMSPVA_RENT,
)
from factory.errors import FactoryError
from factory.providers.base import SmsProvider
from factory.providers.fake import FakeSmsProvider
from factory.providers.smspva import build_smspva_provider
from factory.providers.smspva_rent import build_smspva_rent_provider
from factory.registrar.base import TelegramRegistrar
from factory.registrar.fake import FakeRegistrar
from factory.registrar.telethon import TelethonRegistrar


def get_sms_provider(settings: Settings) -> SmsProvider:
    """Return the SMS provider selected by `settings.account_factory_provider`.

    `smspva` (Activation) and `smspva_rent` (Rental, TASK-143 — real-SIM opt29 numbers
    Telegram accepts) both require a non-empty `smspva_api_key` — an empty key raises
    `FactoryError` rather than silently degrading to the fake (which would mask a
    misconfiguration). Any other value (including the default `fake`) → `FakeSmsProvider`.
    """
    if settings.account_factory_provider == ACCOUNT_FACTORY_PROVIDER_SMSPVA:
        if not settings.smspva_api_key:
            raise FactoryError("ACCOUNT_FACTORY_PROVIDER=smspva but SMSPVA_API_KEY is empty")
        return build_smspva_provider(api_key=settings.smspva_api_key)
    if settings.account_factory_provider == ACCOUNT_FACTORY_PROVIDER_SMSPVA_RENT:
        if not settings.smspva_api_key:
            raise FactoryError("ACCOUNT_FACTORY_PROVIDER=smspva_rent but SMSPVA_API_KEY is empty")
        return build_smspva_rent_provider(
            api_key=settings.smspva_api_key,
            dtype=settings.account_factory_rent_dtype,
            dcount=settings.account_factory_rent_dcount,
        )
    return FakeSmsProvider()


def get_registrar(settings: Settings) -> TelegramRegistrar:
    """Return the Telegram registrar for the selected provider.

    The real `TelethonRegistrar` is used ONLY when an SMSPVA provider is selected — either
    Activation (`smspva`) OR Rental (`smspva_rent`, TASK-143) — AND the telegram api creds
    (`telegram_api_id`/`telegram_api_hash`) are present; otherwise the deterministic
    `FakeRegistrar` is returned. The rental path MUST get the real registrar: it leases a
    real SIM, so registering against the fake would burn rental money with no real Telegram
    account created.
    """
    if (
        settings.account_factory_provider
        in (ACCOUNT_FACTORY_PROVIDER_SMSPVA, ACCOUNT_FACTORY_PROVIDER_SMSPVA_RENT)
        and settings.telegram_api_id is not None
        and settings.telegram_api_hash is not None
    ):
        return TelethonRegistrar(
            api_id=settings.telegram_api_id, api_hash=settings.telegram_api_hash
        )
    return FakeRegistrar()
