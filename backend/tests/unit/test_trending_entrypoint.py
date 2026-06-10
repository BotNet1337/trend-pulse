"""Unit tests: trending module entrypoint + topic sanitization (TASK-039 fix-cycle).

Tests:
- api.trending.__main__ exposes a callable `main` (guards against entrypoint drift).
- _sanitize_topic_label strips URLs, @-handles, and emails; caps to TRENDING_LABEL_MAX_LEN.
- limit=0 (non-positive) → 422 via ge=1 Query constraint (router boundary).
"""

import importlib

from fastapi.testclient import TestClient

from api.trending.service import TRENDING_LABEL_MAX_LEN, _sanitize_topic_label

# ─── Fix 1: __main__.main entrypoint guard ────────────────────────────────────


def test_trending_main_module_exposes_callable_main() -> None:
    """api.trending.__main__ must expose a callable `main`.

    Guards against entrypoint drift: if the CLI is accidentally moved or renamed,
    `make showcase-init` (which runs `python -m api.trending`) would silently
    do nothing. This assertion is the cheap guard that catches that.
    """
    module = importlib.import_module("api.trending.__main__")
    assert hasattr(module, "main"), "api.trending.__main__ must have a `main` attribute"
    assert callable(module.main), "api.trending.__main__.main must be callable"


# ─── Fix 2: topic sanitization ────────────────────────────────────────────────


def test_sanitize_strips_https_url() -> None:
    """URLs starting with https:// are removed."""
    result = _sanitize_topic_label("Покупайте крипту тут https://t.me/scam срочно")
    assert "https://" not in result
    assert "t.me/scam" not in result


def test_sanitize_strips_http_url() -> None:
    """URLs starting with http:// are removed."""
    result = _sanitize_topic_label("сигнал http://example.com/pump дешево")
    assert "http://" not in result


def test_sanitize_strips_bare_tme_link() -> None:
    """Bare t.me/ links (no scheme) are removed."""
    result = _sanitize_topic_label("подписывайся t.me/pumpgroup срочно")
    assert "t.me/" not in result


def test_sanitize_strips_at_handles() -> None:
    """@-handles are removed."""
    result = _sanitize_topic_label("крипта @pumpgroup @scamchannel растёт")
    assert "@pumpgroup" not in result
    assert "@scamchannel" not in result


def test_sanitize_strips_email_addresses() -> None:
    """Email addresses are removed."""
    result = _sanitize_topic_label("пишите admin@scam.io за сигналами")
    assert "admin@scam.io" not in result


def test_sanitize_realistic_raw_topic() -> None:
    """Realistic raw topic containing URL + @handle → neither appears in output."""
    raw = "Покупайте крипту тут https://t.me/scam @pumpgroup срочно акция"
    result = _sanitize_topic_label(raw)
    assert "https://" not in result
    assert "t.me/scam" not in result
    assert "@pumpgroup" not in result
    # Should still contain the human-readable part
    assert "крипту" in result or "акция" in result or "срочно" in result


def test_sanitize_caps_to_max_len() -> None:
    """Result is always ≤ TRENDING_LABEL_MAX_LEN characters."""
    long_text = "криптовалюта " * 20  # >80 chars
    result = _sanitize_topic_label(long_text)
    assert len(result) <= TRENDING_LABEL_MAX_LEN


def test_sanitize_adds_ellipsis_when_truncated() -> None:
    """Truncated labels end with an ellipsis character."""
    long_text = "x" * 200
    result = _sanitize_topic_label(long_text)
    assert result.endswith("…")
    assert len(result) <= TRENDING_LABEL_MAX_LEN


def test_sanitize_clean_label_unchanged() -> None:
    """A clean topic label passes through without alteration (no false positives)."""
    clean = "Bitcoin price surge"
    result = _sanitize_topic_label(clean)
    assert result == clean


def test_sanitize_collapses_whitespace() -> None:
    """Extra whitespace after stripping tokens is collapsed."""
    result = _sanitize_topic_label("крипта  @handle   сигнал")
    assert "  " not in result
    assert result == result.strip()


# ─── Fix 4: limit ge=1 boundary ───────────────────────────────────────────────


def test_trending_limit_zero_returns_422() -> None:
    """limit=0 (non-positive) → 422 via ge=1 Query constraint."""
    from api.auth.api_key import current_user_or_api_key
    from api.deps import current_user
    from api.main import app
    from storage.models.users import PLAN_FREE, User

    # Minimal stub user for auth override
    stub_user = User(id=1, email="test@example.com", hashed_password="x" * 16, plan=PLAN_FREE)

    app.dependency_overrides[current_user] = lambda: stub_user
    app.dependency_overrides[current_user_or_api_key] = lambda: stub_user
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/trending", params={"pack": "crypto-ru", "limit": 0})
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(current_user_or_api_key, None)


def test_trending_limit_negative_returns_422() -> None:
    """limit=-1 (negative) → 422 via ge=1 Query constraint."""
    from api.auth.api_key import current_user_or_api_key
    from api.deps import current_user
    from api.main import app
    from storage.models.users import PLAN_FREE, User

    stub_user = User(id=1, email="test@example.com", hashed_password="x" * 16, plan=PLAN_FREE)

    app.dependency_overrides[current_user] = lambda: stub_user
    app.dependency_overrides[current_user_or_api_key] = lambda: stub_user
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/trending", params={"pack": "crypto-ru", "limit": -1})
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(current_user_or_api_key, None)
