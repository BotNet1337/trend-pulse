"""Unit tests for reCAPTCHA verification (api.auth.captcha).

No network: the httpx call is monkeypatched. Covers the three branches that
matter for sign-up: disabled (local dev), enabled+valid, enabled+invalid, plus
fail-closed on a network error and a missing token.
"""

import pytest

from api.auth import captcha as captcha_mod
from config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """get_settings is lru_cached — reset it around each test that tweaks env."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_disabled_when_no_secret_always_passes(monkeypatch):
    monkeypatch.setenv("RECAPTCHA_SECRET_KEY", "")
    get_settings.cache_clear()
    assert captcha_mod.recaptcha_enabled() is False
    # Even with no token, a disabled CAPTCHA never blocks sign-up.
    assert await captcha_mod.verify_recaptcha(None) is True
    assert await captcha_mod.verify_recaptcha("anything") is True


@pytest.mark.asyncio
async def test_enabled_missing_token_fails(monkeypatch):
    monkeypatch.setenv("RECAPTCHA_SECRET_KEY", "secret")
    get_settings.cache_clear()
    assert captcha_mod.recaptcha_enabled() is True
    assert await captcha_mod.verify_recaptcha(None) is False
    assert await captcha_mod.verify_recaptcha("") is False


@pytest.mark.asyncio
async def test_enabled_valid_token_passes(monkeypatch):
    monkeypatch.setenv("RECAPTCHA_SECRET_KEY", "secret")
    get_settings.cache_clear()

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"success": True}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(captcha_mod.httpx, "AsyncClient", lambda *a, **k: _Client())
    assert await captcha_mod.verify_recaptcha("good-token") is True


@pytest.mark.asyncio
async def test_enabled_rejected_token_fails(monkeypatch):
    monkeypatch.setenv("RECAPTCHA_SECRET_KEY", "secret")
    get_settings.cache_clear()

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"success": False, "error-codes": ["invalid-input-response"]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(captcha_mod.httpx, "AsyncClient", lambda *a, **k: _Client())
    assert await captcha_mod.verify_recaptcha("bad-token") is False


@pytest.mark.asyncio
async def test_enabled_network_error_fails_closed(monkeypatch):
    monkeypatch.setenv("RECAPTCHA_SECRET_KEY", "secret")
    get_settings.cache_clear()

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            raise RuntimeError("network down")

    monkeypatch.setattr(captcha_mod.httpx, "AsyncClient", lambda *a, **k: _Client())
    # Fail closed: an infra hiccup must not let a bot through when CAPTCHA is on.
    assert await captcha_mod.verify_recaptcha("token") is False
