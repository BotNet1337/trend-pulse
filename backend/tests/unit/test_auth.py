"""Unit tests for the fastapi-users auth wiring (no live Postgres required).

These cover the parts that do NOT need a real database:
- AC1 (JWT half): a token minted by the configured `JWTStrategy` decodes with the
  settings secret and carries `sub == user_id`.
- AC5: a wrong-password login attempt is rejected (verified at the PasswordHelper
  level — the library primitive fastapi-users uses; no user-enumeration leak).
- AC6: constructing `Settings` without the required secret env vars fails fast.

The full DB-backed register -> login -> cookie -> logout -> Google-callback flow
lives in `tests/integration/test_auth_flow.py` (marker `integration`), so
`make ci-fast` stays green without Postgres.
"""

import jwt
import pytest

from api.auth.backend import build_jwt_strategy
from config import Settings


def _settings() -> Settings:
    """Settings with all required secrets present (conftest seeds the env)."""
    return Settings()


async def test_jwt_minted_by_backend_decodes_with_settings_secret() -> None:
    """AC1 (JWT half): the configured strategy issues a JWT whose `sub` is the user id."""
    settings = _settings()
    strategy = build_jwt_strategy(settings)

    class _User:
        id = 4242

    token = await strategy.write_token(_User())  # type: ignore[arg-type]

    decoded = jwt.decode(
        token,
        settings.jwt_secret,
        audience=["fastapi-users:auth"],
        algorithms=["HS256"],
    )
    assert decoded["sub"] == "4242"
    assert "exp" in decoded


async def test_tampered_jwt_does_not_decode_with_settings_secret() -> None:
    """A token signed with a different secret must NOT validate (AC2/edge: 401 path)."""
    settings = _settings()
    forged = jwt.encode(
        {"sub": "1", "aud": ["fastapi-users:auth"]},
        "not-the-real-secret",
        algorithm="HS256",
    )
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(
            forged,
            settings.jwt_secret,
            audience=["fastapi-users:auth"],
            algorithms=["HS256"],
        )


def test_wrong_password_is_rejected_by_password_helper() -> None:
    """AC5: the library password primitive rejects a wrong password."""
    from fastapi_users.password import PasswordHelper

    helper = PasswordHelper()
    hashed = helper.hash("correct horse battery staple")

    ok, _ = helper.verify_and_update("wrong-password", hashed)
    assert ok is False

    ok_right, _ = helper.verify_and_update("correct horse battery staple", hashed)
    assert ok_right is True


def test_settings_fail_fast_without_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC6: a missing JWT_SECRET (and friends) makes Settings construction raise."""
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("OAUTH_STATE_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    with pytest.raises(ValueError):
        Settings()
