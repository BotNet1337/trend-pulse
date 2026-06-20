"""TASK-139 — proxy-provider selection-by-env unit tests.

Unset/empty/unknown → `None` (caller falls back to the static pool). `fake` →
`FakeProxyProvider`. `mobileproxy` + token → `MobileProxyProvider`; `mobileproxy`
with an empty token → `FactoryError` (fail fast, no silent fallback).
"""

from __future__ import annotations

import pytest

from config import Settings
from factory.constants import (
    ACCOUNT_FACTORY_PROXY_PROVIDER_FAKE,
    ACCOUNT_FACTORY_PROXY_PROVIDER_MOBILEPROXY,
)
from factory.errors import FactoryError
from factory.proxy.factory import get_proxy_provider
from factory.proxy.fake import FakeProxyProvider
from factory.proxy.mobileproxy import MobileProxyProvider


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "jwt_secret": "t",
        "oauth_state_secret": "t",
        "google_client_id": "t",
        "google_client_secret": "t",
    }
    base.update(overrides)
    return Settings.model_construct(**base)


def test_unset_provider_returns_none() -> None:
    settings = _settings(account_factory_proxy_provider="")
    assert get_proxy_provider(settings) is None


def test_unknown_provider_returns_none() -> None:
    settings = _settings(account_factory_proxy_provider="totally-unknown")
    assert get_proxy_provider(settings) is None


def test_fake_provider_selected() -> None:
    settings = _settings(account_factory_proxy_provider=ACCOUNT_FACTORY_PROXY_PROVIDER_FAKE)
    assert isinstance(get_proxy_provider(settings), FakeProxyProvider)


def test_mobileproxy_selected_when_token_set() -> None:
    settings = _settings(
        account_factory_proxy_provider=ACCOUNT_FACTORY_PROXY_PROVIDER_MOBILEPROXY,
        mobileproxy_api_token="real-token",
    )
    assert isinstance(get_proxy_provider(settings), MobileProxyProvider)


def test_mobileproxy_without_token_raises() -> None:
    settings = _settings(
        account_factory_proxy_provider=ACCOUNT_FACTORY_PROXY_PROVIDER_MOBILEPROXY,
        mobileproxy_api_token="",
    )
    with pytest.raises(FactoryError):
        get_proxy_provider(settings)


def test_mobileproxy_whitespace_token_raises() -> None:
    settings = _settings(
        account_factory_proxy_provider=ACCOUNT_FACTORY_PROXY_PROVIDER_MOBILEPROXY,
        mobileproxy_api_token="   ",
    )
    with pytest.raises(FactoryError):
        get_proxy_provider(settings)
