"""AC6: /ready is 200 when deps healthy, 503 when a dep is unreachable.

`/health` stays a pure 200 regardless (liveness vs readiness are separate). The DB
and Redis checks are monkeypatched so the test is DB/network-free.
"""

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes import ops

_HTTP_OK = 200
_HTTP_UNAVAILABLE = 503


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_ready_200_when_all_deps_ok(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ops, "_check_db", lambda: True)
    monkeypatch.setattr(ops, "_check_redis", lambda: True)
    response = client.get("/ready")
    assert response.status_code == _HTTP_OK
    assert response.json() == {"db": "ok", "redis": "ok"}


def test_ready_503_when_db_unreachable(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ops, "_check_db", lambda: False)
    monkeypatch.setattr(ops, "_check_redis", lambda: True)
    response = client.get("/ready")
    assert response.status_code == _HTTP_UNAVAILABLE
    body = response.json()
    assert body["db"] == "unreachable"
    assert body["redis"] == "ok"


def test_ready_503_when_redis_unreachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ops, "_check_db", lambda: True)
    monkeypatch.setattr(ops, "_check_redis", lambda: False)
    response = client.get("/ready")
    assert response.status_code == _HTTP_UNAVAILABLE
    assert response.json()["redis"] == "unreachable"


def test_health_stays_200_regardless(client: TestClient) -> None:
    """/health is pure liveness and must not depend on DB/Redis readiness."""
    response = client.get("/health")
    assert response.status_code == _HTTP_OK
    assert response.json() == {"status": "ok"}
