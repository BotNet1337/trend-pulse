"""TASK-133 — provider/registrar selection-by-env unit tests.

Default settings → fakes (CI-safe). `smspva` + key → real provider; `smspva` +
telegram api creds → real registrar (isinstance only, no network). `smspva` with
an empty key → FactoryError (fail fast, no silent fallback to fake).
"""

from __future__ import annotations

import pytest

from config import Settings
from factory.constants import (
    ACCOUNT_FACTORY_PROVIDER_FAKE,
    ACCOUNT_FACTORY_PROVIDER_SMSPVA,
    ACCOUNT_FACTORY_PROVIDER_SMSPVA_RENT,
)
from factory.errors import FactoryError
from factory.providers.factory import get_registrar, get_sms_provider
from factory.providers.fake import FakeSmsProvider
from factory.providers.smspva import SmsPvaProvider
from factory.providers.smspva_rent import SmsPvaRentProvider
from factory.registrar.fake import FakeRegistrar
from factory.registrar.telethon import TelethonRegistrar


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "jwt_secret": "t",
        "oauth_state_secret": "t",
        "google_client_id": "t",
        "google_client_secret": "t",
    }
    base.update(overrides)
    return Settings.model_construct(**base)


def test_default_settings_return_fakes() -> None:
    settings = _settings(account_factory_provider=ACCOUNT_FACTORY_PROVIDER_FAKE)
    assert isinstance(get_sms_provider(settings), FakeSmsProvider)
    assert isinstance(get_registrar(settings), FakeRegistrar)


def test_smspva_provider_selected_when_key_set() -> None:
    settings = _settings(
        account_factory_provider=ACCOUNT_FACTORY_PROVIDER_SMSPVA,
        smspva_api_key="real-key",
    )
    assert isinstance(get_sms_provider(settings), SmsPvaProvider)


def test_smspva_without_key_raises() -> None:
    settings = _settings(
        account_factory_provider=ACCOUNT_FACTORY_PROVIDER_SMSPVA,
        smspva_api_key="",
    )
    with pytest.raises(FactoryError):
        get_sms_provider(settings)


def test_smspva_rent_provider_selected_when_key_set() -> None:
    settings = _settings(
        account_factory_provider=ACCOUNT_FACTORY_PROVIDER_SMSPVA_RENT,
        smspva_api_key="real-key",
    )
    assert isinstance(get_sms_provider(settings), SmsPvaRentProvider)


def test_smspva_rent_without_key_raises() -> None:
    settings = _settings(
        account_factory_provider=ACCOUNT_FACTORY_PROVIDER_SMSPVA_RENT,
        smspva_api_key="",
    )
    with pytest.raises(FactoryError):
        get_sms_provider(settings)


def test_real_registrar_selected_when_api_creds_present() -> None:
    settings = _settings(
        account_factory_provider=ACCOUNT_FACTORY_PROVIDER_SMSPVA,
        smspva_api_key="real-key",
        telegram_api_id=12345,
        telegram_api_hash="hash",
    )
    assert isinstance(get_registrar(settings), TelethonRegistrar)


def test_registrar_falls_back_to_fake_without_api_creds() -> None:
    settings = _settings(
        account_factory_provider=ACCOUNT_FACTORY_PROVIDER_SMSPVA,
        smspva_api_key="real-key",
        telegram_api_id=None,
        telegram_api_hash=None,
    )
    assert isinstance(get_registrar(settings), FakeRegistrar)


def test_real_registrar_selected_for_rent_when_api_creds_present() -> None:
    # The rental path leases a real SIM — it MUST get the real registrar (registering
    # against the fake would burn rental money with no real Telegram account created).
    settings = _settings(
        account_factory_provider=ACCOUNT_FACTORY_PROVIDER_SMSPVA_RENT,
        smspva_api_key="real-key",
        telegram_api_id=12345,
        telegram_api_hash="hash",
    )
    assert isinstance(get_registrar(settings), TelethonRegistrar)


def test_rent_registrar_falls_back_to_fake_without_api_creds() -> None:
    settings = _settings(
        account_factory_provider=ACCOUNT_FACTORY_PROVIDER_SMSPVA_RENT,
        smspva_api_key="real-key",
        telegram_api_id=None,
        telegram_api_hash=None,
    )
    assert isinstance(get_registrar(settings), FakeRegistrar)
