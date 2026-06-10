"""Unit tests for Settings field validators — TASK-042.

Tests for the ``public_base_url`` validator:
- Empty string: allowed (feature off — graceful degradation).
- Valid https://: allowed.
- http://localhost: allowed (dev G2 runs).
- http://127.0.0.1: allowed (dev G2 runs).
- http://example.com: rejected (non-TLS prod URL).
- http://evil.com: rejected.
- ftp://: rejected.

No live DB/Redis needed — pure Settings instantiation.
"""

import pytest
from pydantic import ValidationError


def _make_settings(public_base_url: str) -> object:
    """Create a Settings instance with a specific public_base_url.

    Uses the conftest-seeded env (JWT_SECRET etc. present) and overrides
    only public_base_url.
    """
    from config import Settings

    return Settings(public_base_url=public_base_url)


class TestPublicBaseUrlValidator:
    """public_base_url field validator (TASK-042 MEDIUM security fix)."""

    def test_empty_string_allowed(self) -> None:
        """Empty string disables feedback buttons (graceful degradation)."""
        s = _make_settings("")
        assert s.public_base_url == ""  # type: ignore[union-attr]

    def test_valid_https_allowed(self) -> None:
        """https:// is always accepted."""
        s = _make_settings("https://foresignal.biz")
        assert s.public_base_url == "https://foresignal.biz"  # type: ignore[union-attr]

    def test_https_with_path_allowed(self) -> None:
        """https:// with a path suffix is accepted."""
        s = _make_settings("https://app.example.com")
        assert s.public_base_url == "https://app.example.com"  # type: ignore[union-attr]

    def test_http_localhost_allowed(self) -> None:
        """http://localhost is allowed (dev G2 — local ASGI without TLS)."""
        s = _make_settings("http://localhost:8000")
        assert s.public_base_url == "http://localhost:8000"  # type: ignore[union-attr]

    def test_http_localhost_no_port_allowed(self) -> None:
        """http://localhost without explicit port is allowed."""
        s = _make_settings("http://localhost")
        assert s.public_base_url == "http://localhost"  # type: ignore[union-attr]

    def test_http_127_0_0_1_allowed(self) -> None:
        """http://127.0.0.1 is allowed (loopback — dev G2)."""
        s = _make_settings("http://127.0.0.1:8000")
        assert s.public_base_url == "http://127.0.0.1:8000"  # type: ignore[union-attr]

    def test_http_non_local_rejected(self) -> None:
        """http://example.com must be rejected — non-TLS remote URL."""
        with pytest.raises(ValidationError) as exc_info:
            _make_settings("http://example.com")
        assert "https://" in str(exc_info.value) or "non-local" in str(exc_info.value)

    def test_http_prod_domain_rejected(self) -> None:
        """http://foresignal.biz must be rejected — prod must use HTTPS."""
        with pytest.raises(ValidationError):
            _make_settings("http://foresignal.biz")

    def test_ftp_scheme_rejected(self) -> None:
        """Non-http/https scheme is rejected."""
        with pytest.raises(ValidationError):
            _make_settings("ftp://foresignal.biz")
