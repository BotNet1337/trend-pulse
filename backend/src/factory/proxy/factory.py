"""Env-based selection of the ProxyProvider impl (TASK-139).

`ACCOUNT_FACTORY_PROXY_PROVIDER` chooses the impl. Unset/empty/unknown → `None`
(the caller keeps today's static-pool path — zero behavior change). `fake` →
`FakeProxyProvider` (CI/this env network-free). `mobileproxy` requires a non-empty
`MOBILEPROXY_API_TOKEN` (fail fast via `FactoryError` — never a silent fallback to the
fake, which would mask a misconfiguration).
"""

from __future__ import annotations

from config import Settings
from factory.constants import (
    ACCOUNT_FACTORY_PROXY_PROVIDER_FAKE,
    ACCOUNT_FACTORY_PROXY_PROVIDER_MOBILEPROXY,
)
from factory.errors import FactoryError
from factory.proxy.base import ProxyProvider
from factory.proxy.fake import FakeProxyProvider
from factory.proxy.mobileproxy import build_mobileproxy_provider


def get_proxy_provider(settings: Settings) -> ProxyProvider | None:
    """Return the dynamic proxy provider selected by `account_factory_proxy_provider`.

    Unset/empty/unknown → `None` (caller falls back to the static pool). `fake` →
    `FakeProxyProvider`. `mobileproxy` requires a non-empty (non-whitespace)
    `mobileproxy_api_token` — an empty token raises `FactoryError` rather than silently
    degrading to the fake.
    """
    provider = settings.account_factory_proxy_provider
    if provider == ACCOUNT_FACTORY_PROXY_PROVIDER_FAKE:
        return FakeProxyProvider()
    if provider == ACCOUNT_FACTORY_PROXY_PROVIDER_MOBILEPROXY:
        token = settings.mobileproxy_api_token.strip()
        if not token:
            raise FactoryError(
                "ACCOUNT_FACTORY_PROXY_PROVIDER=mobileproxy but MOBILEPROXY_API_TOKEN is empty"
            )
        return build_mobileproxy_provider(api_key=token)
    # Unset/empty/unknown → no dynamic provider; the caller uses the static pool.
    return None
