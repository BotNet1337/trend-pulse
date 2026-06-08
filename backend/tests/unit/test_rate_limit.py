"""AC4: requests within the limit -> 200; over the limit -> 429 with a clear body.

DB/network-free: a dedicated FastAPI app wires a low-limit, in-memory (`memory://`)
slowapi limiter so the over-limit path is deterministic without Redis. The 429
handler and key function are the SAME ones `api.main` registers in production.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from api.rate_limit import rate_limit_handler, rate_limit_key

_HTTP_OK = 200
_HTTP_TOO_MANY = 429
_LIMIT = 2


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    limiter = Limiter(
        key_func=rate_limit_key,
        default_limits=[f"{_LIMIT}/minute"],
        storage_uri="memory://",
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {"ok": "yes"}

    return TestClient(app)


def test_within_limit_returns_200(client: TestClient) -> None:
    for _ in range(_LIMIT):
        assert client.get("/ping").status_code == _HTTP_OK


def test_over_limit_returns_429_with_clear_body(client: TestClient) -> None:
    for _ in range(_LIMIT):
        client.get("/ping")
    response = client.get("/ping")
    assert response.status_code == _HTTP_TOO_MANY
    body = response.json()
    assert "detail" in body
    assert "rate limit exceeded" in body["detail"]


# --- key function: authenticated requests key by user, not IP (AC4) ---
import jwt  # noqa: E402
from starlette.requests import Request  # noqa: E402

from api.auth.backend import cookie_transport  # noqa: E402
from config import get_settings  # noqa: E402


def _request(*, cookie: str | None = None, ip: str = "1.2.3.4") -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if cookie is not None:
        headers.append((b"cookie", f"{cookie_transport.cookie_name}={cookie}".encode()))
    return Request({"type": "http", "headers": headers, "client": (ip, 1234), "state": {}})


def _auth_token(user_id: int) -> str:
    return jwt.encode(
        {"sub": str(user_id), "aud": ["fastapi-users:auth"]},
        get_settings().jwt_secret,
        algorithm="HS256",
    )


def test_key_is_per_user_even_on_a_shared_ip() -> None:
    # Two authenticated users behind the SAME IP must get independent buckets.
    a = rate_limit_key(_request(cookie=_auth_token(1), ip="9.9.9.9"))
    b = rate_limit_key(_request(cookie=_auth_token(2), ip="9.9.9.9"))
    assert a == "user:1"
    assert b == "user:2"
    assert a != b


def test_key_falls_back_to_ip_when_anonymous() -> None:
    assert rate_limit_key(_request(ip="5.6.7.8")) == "ip:5.6.7.8"


def test_key_falls_back_to_ip_on_invalid_token() -> None:
    assert rate_limit_key(_request(cookie="not-a-jwt", ip="5.6.7.8")) == "ip:5.6.7.8"
