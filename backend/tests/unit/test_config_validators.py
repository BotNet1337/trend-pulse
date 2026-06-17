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


class TestBeatHeartbeatTtlValidator:
    """beat_heartbeat_ttl_seconds validator (TASK-098 reliability)."""

    def test_default_exceeds_max_interval(self) -> None:
        """Default 600s > beat max_interval 300s — accepted."""
        from config import Settings

        assert Settings().beat_heartbeat_ttl_seconds == 600

    def test_above_max_interval_allowed(self) -> None:
        """Any TTL strictly above 300s is accepted."""
        from config import Settings

        assert Settings(beat_heartbeat_ttl_seconds=301).beat_heartbeat_ttl_seconds == 301

    def test_at_or_below_max_interval_rejected(self) -> None:
        """TTL <= 300s would let a healthy beat flap → rejected at startup."""
        from config import Settings

        for bad in (300, 60, 0):
            with pytest.raises(ValidationError):
                Settings(beat_heartbeat_ttl_seconds=bad)


class TestClusterMergeCosineThresholdInvariant:
    """cluster_merge_cosine_threshold <= cluster_cosine_threshold (TASK-123).

    The loose cross-channel merge tier must never be STRICTER than the tight
    intra-batch grouping/dedup tier — otherwise two-tier clustering is meaningless.
    Enforced by a model_validator(mode="after") at Settings construction.
    """

    def test_default_is_loose_merge_threshold(self) -> None:
        """Default loose merge threshold is 0.65 (not the tight 0.75)."""
        from config import Settings

        s = Settings()
        assert s.cluster_merge_cosine_threshold == pytest.approx(0.65)
        # And it is <= the tight intra-batch threshold (default 0.75).
        assert s.cluster_merge_cosine_threshold <= s.cluster_cosine_threshold

    def test_equal_to_tight_allowed(self) -> None:
        """loose == tight (both 0.75) is the safe-fallback / A-B point — accepted."""
        from config import Settings

        s = Settings(cluster_merge_cosine_threshold=0.75, cluster_cosine_threshold=0.75)
        assert s.cluster_merge_cosine_threshold == pytest.approx(0.75)

    def test_looser_than_tight_allowed(self) -> None:
        """A merge threshold below the tight threshold is accepted (the whole point)."""
        from config import Settings

        s = Settings(cluster_merge_cosine_threshold=0.62, cluster_cosine_threshold=0.75)
        assert s.cluster_merge_cosine_threshold == pytest.approx(0.62)

    def test_stricter_than_tight_rejected(self) -> None:
        """loose > tight (0.80 > 0.75) must raise — two-tier inversion is misconfig."""
        from config import Settings

        with pytest.raises(ValidationError):
            Settings(cluster_merge_cosine_threshold=0.80, cluster_cosine_threshold=0.75)

    def test_env_override_above_tight_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC3: env CLUSTER_MERGE_COSINE_THRESHOLD=0.80 (> tight 0.75) → ValidationError."""
        from config import Settings

        monkeypatch.setenv("CLUSTER_MERGE_COSINE_THRESHOLD", "0.80")
        with pytest.raises(ValidationError):
            Settings()


class TestActiveEnvPoolSessions:
    """Store-only by default: the env pool floor is opt-in (TASK store-only)."""

    def test_env_sessions_ignored_by_default(self) -> None:
        from config import Settings, active_env_pool_sessions

        s = Settings(telegram_pool_sessions="sessA,sessB")
        # Default (telegram_pool_use_env_sessions=False) → env fully ignored.
        assert s.telegram_pool_use_env_sessions is False
        assert active_env_pool_sessions(s) == []

    def test_env_sessions_used_when_floor_enabled(self) -> None:
        from config import Settings, active_env_pool_sessions, telegram_pool_sessions

        s = Settings(
            telegram_pool_sessions="sessA, sessB",
            telegram_pool_use_env_sessions=True,
        )
        assert active_env_pool_sessions(s) == ["sessA", "sessB"]
        # The raw parser is unchanged regardless of the floor flag.
        assert telegram_pool_sessions(s) == ["sessA", "sessB"]

    def test_empty_env_stays_empty_when_enabled(self) -> None:
        from config import Settings, active_env_pool_sessions

        s = Settings(telegram_pool_use_env_sessions=True)
        assert active_env_pool_sessions(s) == []
