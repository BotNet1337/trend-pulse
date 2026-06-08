"""AC1 RED→GREEN anchor: GET /health returns 200 + {"status": "ok"}."""

from fastapi.testclient import TestClient

from api.main import app

_HTTP_OK = 200


def test_health_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == _HTTP_OK
    assert response.json() == {"status": "ok"}
