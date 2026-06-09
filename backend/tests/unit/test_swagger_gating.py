"""Unit tests for Swagger/Redoc/OpenAPI gating via SWAGGER_ENABLE env flag (TASK-019 AC1).

RED-anchor: written BEFORE the gating implementation.  At baseline FastAPI is
constructed without docs_url/redoc_url/openapi_url overrides → all three paths
are open regardless of the env flag → test_docs_disabled will FAIL (RED).

After adding `swagger_enable: bool = False` to Settings and wiring `_docs_urls`
into the FastAPI constructor in api/main.py the tests become GREEN.

Approach: monkeypatch SWAGGER_ENABLE, clear the lru_cache on get_settings, then
reload api.main so FastAPI is re-instantiated with fresh settings.  autouse
fixture restores the cache + module state after each test so other tests are
not affected.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

from config import get_settings

_HTTP_OK = 200
_HTTP_NOT_FOUND = 404
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


def _app_with_swagger(monkeypatch: pytest.MonkeyPatch, *, enabled: bool) -> object:
    """Return a freshly-constructed FastAPI app with SWAGGER_ENABLE set."""
    import api.main

    monkeypatch.setenv("SWAGGER_ENABLE", "true" if enabled else "false")
    get_settings.cache_clear()
    module = importlib.reload(api.main)
    return module.app


@pytest.fixture(autouse=True)
def _restore_settings() -> object:
    """Restore settings cache and reload api.main after each test."""
    import api.main

    yield
    get_settings.cache_clear()
    importlib.reload(api.main)


def test_docs_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """When SWAGGER_ENABLE=false all three docs paths must return 404."""
    app = _app_with_swagger(monkeypatch, enabled=False)
    client = TestClient(app, raise_server_exceptions=True)
    for path in _DOCS_PATHS:
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == _HTTP_NOT_FOUND, (
            f"Expected 404 for {path} when SWAGGER_ENABLE=false, got {resp.status_code}"
        )


def test_docs_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """When SWAGGER_ENABLE=true all three docs paths must return 200."""
    app = _app_with_swagger(monkeypatch, enabled=True)
    client = TestClient(app, raise_server_exceptions=True)
    for path in _DOCS_PATHS:
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == _HTTP_OK, (
            f"Expected 200 for {path} when SWAGGER_ENABLE=true, got {resp.status_code}"
        )
