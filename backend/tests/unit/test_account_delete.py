"""AC3 (unit): `delete_user` issues a single cascading DELETE on `users`.

The cascade/no-orphan behaviour itself is proven by the integration test against a
real Postgres; here we assert the service issues exactly one set-based DELETE keyed
by the user id (bind param, never f-string SQL) and that the endpoint is auth-gated.
"""

from fastapi import status
from fastapi.testclient import TestClient

from api.main import app


class _FakeResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _FakeSession:
    def __init__(self, rowcount: int) -> None:
        self._rowcount = rowcount
        self.executed: list[object] = []

    def execute(self, statement: object) -> _FakeResult:
        self.executed.append(statement)
        return _FakeResult(self._rowcount)


def test_delete_user_issues_single_delete_on_users() -> None:
    from compliance.account import delete_user

    session = _FakeSession(rowcount=1)
    deleted = delete_user(session, user_id=42)

    assert deleted == 1
    assert len(session.executed) == 1
    compiled = str(session.executed[0])
    assert "DELETE FROM users" in compiled
    # Keyed by id with a bind param (no literal 42 in the SQL text).
    assert "WHERE users.id" in compiled
    assert "42" not in compiled


def test_delete_account_requires_auth() -> None:
    """Unauthenticated DELETE /v1/account -> 401 (tenant-scoped, no anonymous erase)."""
    client = TestClient(app)
    response = client.delete("/v1/account")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
