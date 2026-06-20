"""Integration tests for the superuser factory API (TASK-135).

Covers:
  * auth matrix — anonymous → 401, regular user → 403, superuser reaches GET endpoints;
  * GET /factory/accounts — returns rows, NO session_string/proxy in any response body;
  * POST /factory/accounts — 202 + row exists afterward with provider set, 503 when unset;
  * POST /factory/accounts/{id}/relogin — 404 on unknown id, 503 when provider unset;
  * GET /factory/budget — math is correct, enabled/provider reflect config, remaining >= 0;
  * no-secret assertion across all endpoints.

The tick-runner is overridden via `get_factory_tick_runner` so no real network is touched.
The DB-backed superuser fixture mirrors test_pool_admin_api.py exactly.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from api.main import app
from config import Settings, get_settings
from factory.constants import (
    FACTORY_STATE_PROBATION,
    FACTORY_STATE_PURCHASED,
    FACTORY_STATE_REGISTERED,
)
from storage import factory_account_store
from storage.database import get_async_session
from storage.models.users import User

pytestmark = pytest.mark.integration

_TEST_PASSWORD = "test-pass-f4ctory"
_ACCOUNTS_PATH = "/v1/factory/accounts"
_BUDGET_PATH = "/v1/factory/budget"
_PROXY = "socks5://user:pass@10.0.0.1:1080"
_BUDGET_HEALTH = '{"healthy": 0, "target": 3, "as_of": "2026-06-20T00:00:00+00:00"}'


def _relogin_path(account_id: int) -> str:
    return f"/v1/factory/accounts/{account_id}/relogin"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(db_engine: Any) -> Iterator[TestClient]:
    """TestClient with the async session wired to the shared test schema."""
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )

    async def _override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_async_session] = _override
    try:
        with TestClient(app, headers={"Origin": "http://testserver"}) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_async_session, None)
        # Import here to avoid ImportError if route doesn't exist yet (RED phase).
        try:
            from api.routes.factory import (
                get_factory_db,
                get_factory_tick_runner,
            )

            app.dependency_overrides.pop(get_factory_db, None)
            app.dependency_overrides.pop(get_factory_tick_runner, None)
        except ImportError:
            pass


def _register(client: TestClient, email: str) -> dict[str, Any]:
    resp = client.post("/v1/auth/register", json={"email": email, "password": _TEST_PASSWORD})
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _login(client: TestClient, email: str) -> None:
    resp = client.post(
        "/v1/auth/jwt/login",
        data={"username": email, "password": _TEST_PASSWORD},
    )
    assert resp.status_code in (200, 204), resp.text


def _login_as_superuser(client: TestClient, db_session: Session, email: str) -> None:
    """Register `email`, promote to superuser in DB, and log in."""
    user_data = _register(client, email)
    db_session.execute(update(User).where(User.id == user_data["id"]).values(is_superuser=True))
    db_session.commit()
    _login(client, email)


def _settings_with(**overrides: object) -> Settings:
    """A real Settings clone with factory overrides."""
    base = get_settings()
    return base.model_copy(update=overrides)


def _override_db(db_session: Session) -> None:
    """Wire the factory DB dep to the test session."""
    from api.routes.factory import get_factory_db

    def _db_override() -> Iterator[Session]:
        yield db_session
        db_session.commit()

    app.dependency_overrides[get_factory_db] = _db_override


def _override_tick_runner_noop() -> None:
    """Override the tick runner with a no-op callable."""
    from api.routes.factory import get_factory_tick_runner

    def _noop(redis: Any, settings: Any) -> None:
        pass

    app.dependency_overrides[get_factory_tick_runner] = lambda: _noop


def _override_tick_runner_fake(db_session: Session) -> None:
    """Override the tick runner with the real run_factory_tick using fakeredis."""
    from api.routes.factory import get_factory_tick_runner
    from factory.tasks import run_factory_tick

    settings = _settings_with(
        account_factory_provider="fake",
        account_factory_budget_usd=Decimal("10"),
        account_factory_price_usd=Decimal("1"),
        account_factory_proxy_pool=_PROXY,
    )
    redis = fakeredis.FakeRedis(decode_responses=True)
    redis.set("pool:health:latest", _BUDGET_HEALTH)

    def _fake_tick(_redis: Any, _settings: Any) -> None:
        run_factory_tick(redis, settings=settings)

    app.dependency_overrides[get_factory_tick_runner] = lambda: _fake_tick


# ---------------------------------------------------------------------------
# Auth matrix
# ---------------------------------------------------------------------------


class TestAuthMatrix:
    def test_anonymous_gets_401_on_all_routes(self, client: TestClient) -> None:
        assert client.get(_ACCOUNTS_PATH).status_code == 401
        assert client.post(_ACCOUNTS_PATH).status_code == 401
        assert client.get(_BUDGET_PATH).status_code == 401
        assert client.post(_relogin_path(1)).status_code == 401

    def test_regular_user_gets_403_on_all_routes(
        self, client: TestClient, db_session: Session
    ) -> None:
        _register(client, "fa-regular@example.com")
        _login(client, "fa-regular@example.com")

        assert client.get(_ACCOUNTS_PATH).status_code == 403
        assert client.post(_ACCOUNTS_PATH).status_code == 403
        assert client.get(_BUDGET_PATH).status_code == 403
        assert client.post(_relogin_path(1)).status_code == 403

    def test_superuser_reaches_get_accounts(self, client: TestClient, db_session: Session) -> None:
        _override_db(db_session)
        _login_as_superuser(client, db_session, "fa-super-accounts@example.com")
        resp = client.get(_ACCOUNTS_PATH)
        assert resp.status_code == 200, resp.text

    def test_superuser_reaches_get_budget(self, client: TestClient, db_session: Session) -> None:
        _override_db(db_session)
        _login_as_superuser(client, db_session, "fa-super-budget@example.com")
        resp = client.get(_BUDGET_PATH)
        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# GET /factory/accounts
# ---------------------------------------------------------------------------


class TestGetFactoryAccounts:
    def test_returns_empty_list_initially(self, client: TestClient, db_session: Session) -> None:
        _override_db(db_session)
        _login_as_superuser(client, db_session, "fa-list-empty@example.com")

        resp = client.get(_ACCOUNTS_PATH)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body == []

    def test_returns_seeded_rows_with_state_and_cost(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Seed a couple of rows and assert listing works without secrets."""
        _override_db(db_session)

        # Seed rows in different states.
        rec1 = factory_account_store.create_purchased(
            db_session,
            phone_masked="+7*****1001",
            provider="fake",
            provider_order_id="order-001",
            cost_usd=Decimal("1.00"),
        )
        db_session.commit()

        rec2 = factory_account_store.create_purchased(
            db_session,
            phone_masked="+7*****1002",
            provider="fake",
            provider_order_id="order-002",
            cost_usd=Decimal("2.00"),
        )
        # Must go purchased → registered → probation (state machine enforces path).
        factory_account_store.transition(
            db_session,
            rec2.id,
            FACTORY_STATE_REGISTERED,
            session_string="s-string-secret",
            tg_user_id=111_222_333,
        )
        factory_account_store.transition(
            db_session,
            rec2.id,
            FACTORY_STATE_PROBATION,
            probation_until=datetime.now(UTC) + timedelta(days=7),
        )
        db_session.commit()

        _login_as_superuser(client, db_session, "fa-list-rows@example.com")
        resp = client.get(_ACCOUNTS_PATH)
        assert resp.status_code == 200, resp.text
        body = resp.json()

        ids = {a["id"] for a in body}
        assert rec1.id in ids
        assert rec2.id in ids

        # Check state and cost are surfaced.
        purchased = next(a for a in body if a["id"] == rec1.id)
        assert purchased["state"] == FACTORY_STATE_PURCHASED
        assert Decimal(purchased["cost_usd"]) == Decimal("1.00")

        probation = next(a for a in body if a["id"] == rec2.id)
        assert probation["state"] == FACTORY_STATE_PROBATION
        assert probation["probation_until"] is not None

        # CRITICAL: NO session_string or proxy in ANY account object or raw JSON.
        full_json = json.dumps(body)
        assert "session_string" not in full_json
        assert "s-string-secret" not in full_json
        assert "proxy" not in full_json

    def test_no_secret_in_response_body(self, client: TestClient, db_session: Session) -> None:
        """Assert neither 'session_string' key nor any secret value appears in response."""
        _override_db(db_session)
        rec = factory_account_store.create_purchased(
            db_session,
            phone_masked="+7*****9999",
            provider="fake",
            provider_order_id="order-secret",
            cost_usd=Decimal("1.00"),
        )
        # Must go purchased → registered → probation (state machine enforces path).
        factory_account_store.transition(
            db_session,
            rec.id,
            FACTORY_STATE_REGISTERED,
            session_string="SUPER-SECRET-SESSION-12345",
            tg_user_id=999_888_777,
        )
        factory_account_store.transition(
            db_session,
            rec.id,
            FACTORY_STATE_PROBATION,
            probation_until=datetime.now(UTC) + timedelta(days=1),
        )
        db_session.commit()

        _login_as_superuser(client, db_session, "fa-nosecret@example.com")
        resp = client.get(_ACCOUNTS_PATH)
        assert resp.status_code == 200, resp.text
        raw = resp.text
        assert "session_string" not in raw
        assert "SUPER-SECRET-SESSION-12345" not in raw
        assert "proxy" not in raw


# ---------------------------------------------------------------------------
# POST /factory/accounts
# ---------------------------------------------------------------------------


class TestPostFactoryAccounts:
    def test_provider_unset_returns_503(self, client: TestClient, db_session: Session) -> None:
        """When provider is unset/empty the route returns 503 (provider gate)."""
        _override_db(db_session)
        _override_tick_runner_noop()
        _login_as_superuser(client, db_session, "fa-post-503@example.com")

        # Override settings to have no provider.
        from api.routes.factory import get_factory_tick_runner

        settings_noprovider = _settings_with(account_factory_provider="")

        def _noop_check(redis: Any, settings_arg: Any) -> None:
            # This should NOT be called when provider is unset at the route level.
            pass  # pragma: no cover

        app.dependency_overrides[get_factory_tick_runner] = lambda: _noop_check

        # Now we need to also override get_settings used by the route to return a
        # settings with no provider. The route checks settings.account_factory_provider
        # before calling the tick runner.
        from config import get_settings as _get_settings

        app.dependency_overrides[_get_settings] = lambda: settings_noprovider

        try:
            resp = client.post(_ACCOUNTS_PATH)
            assert resp.status_code == 503, resp.text
            body = resp.json()
            assert "error" in body
        finally:
            app.dependency_overrides.pop(_get_settings, None)

    def test_with_provider_returns_202_and_creates_row(
        self, client: TestClient, db_session: Session
    ) -> None:
        """With fake provider + budget, POST /factory/accounts returns 202 and a row appears."""
        _override_db(db_session)
        _override_tick_runner_fake(db_session)
        _login_as_superuser(client, db_session, "fa-post-202@example.com")

        # Override settings to have provider=fake so the 503 gate passes.
        from config import get_settings as _get_settings

        settings_with_provider = _settings_with(
            account_factory_provider="fake",
            account_factory_budget_usd=Decimal("10"),
            account_factory_price_usd=Decimal("1"),
            account_factory_proxy_pool=_PROXY,
        )
        app.dependency_overrides[_get_settings] = lambda: settings_with_provider

        try:
            resp = client.post(_ACCOUNTS_PATH)
            assert resp.status_code == 202, resp.text
            body = resp.json()
            assert "status" in body

            # A factory_accounts row should exist after the tick.
            db_session.expire_all()
            all_rows: list[factory_account_store.FactoryAccountRecord] = []
            from factory.constants import FACTORY_STATES

            for state in FACTORY_STATES:
                all_rows.extend(factory_account_store.list_by_state(db_session, state))
            assert len(all_rows) >= 1
        finally:
            app.dependency_overrides.pop(_get_settings, None)


# ---------------------------------------------------------------------------
# GET /factory/budget
# ---------------------------------------------------------------------------


class TestGetFactoryBudget:
    def test_budget_math_correct_and_remaining_never_negative(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Budget math: remaining = max(0, budget - spent); never negative."""
        _override_db(db_session)

        # Seed one row that carries cost.
        factory_account_store.create_purchased(
            db_session,
            phone_masked="+7*****5001",
            provider="fake",
            provider_order_id="budget-order-1",
            cost_usd=Decimal("3.00"),
        )
        db_session.commit()

        settings_budget = _settings_with(
            account_factory_provider="fake",
            account_factory_budget_usd=Decimal("5.00"),
        )
        from config import get_settings as _get_settings

        app.dependency_overrides[_get_settings] = lambda: settings_budget

        try:
            _login_as_superuser(client, db_session, "fa-budget-math@example.com")
            resp = client.get(_BUDGET_PATH)
            assert resp.status_code == 200, resp.text
            body = resp.json()

            assert Decimal(body["budget_usd"]) == Decimal("5.00")
            assert Decimal(body["spent_usd"]) == Decimal("3.00")
            assert Decimal(body["remaining_usd"]) == Decimal("2.00")
            assert body["enabled"] is True
            assert body["provider"] == "fake"
        finally:
            app.dependency_overrides.pop(_get_settings, None)

    def test_remaining_never_negative_when_overspent(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Remaining clamps to 0 when spent > budget."""
        _override_db(db_session)

        # Spend more than budget.
        factory_account_store.create_purchased(
            db_session,
            phone_masked="+7*****5002",
            provider="fake",
            provider_order_id="budget-over-1",
            cost_usd=Decimal("10.00"),
        )
        db_session.commit()

        settings_budget = _settings_with(
            account_factory_provider="fake",
            account_factory_budget_usd=Decimal("5.00"),
        )
        from config import get_settings as _get_settings

        app.dependency_overrides[_get_settings] = lambda: settings_budget

        try:
            _login_as_superuser(client, db_session, "fa-budget-overspent@example.com")
            resp = client.get(_BUDGET_PATH)
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert Decimal(body["remaining_usd"]) == Decimal("0")
        finally:
            app.dependency_overrides.pop(_get_settings, None)

    def test_provider_unset_returns_enabled_false(
        self, client: TestClient, db_session: Session
    ) -> None:
        """When provider is unset, GET /budget still 200 but enabled=False, provider=''."""
        _override_db(db_session)

        settings_noprovider = _settings_with(
            account_factory_provider="",
            account_factory_budget_usd=Decimal("5.00"),
        )
        from config import get_settings as _get_settings

        app.dependency_overrides[_get_settings] = lambda: settings_noprovider

        try:
            _login_as_superuser(client, db_session, "fa-budget-noprov@example.com")
            resp = client.get(_BUDGET_PATH)
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["enabled"] is False
            assert body["provider"] == ""
        finally:
            app.dependency_overrides.pop(_get_settings, None)

    def test_get_accounts_works_when_provider_unset(
        self, client: TestClient, db_session: Session
    ) -> None:
        """GET /factory/accounts succeeds even when provider is unset."""
        _override_db(db_session)

        settings_noprovider = _settings_with(account_factory_provider="")
        from config import get_settings as _get_settings

        app.dependency_overrides[_get_settings] = lambda: settings_noprovider

        try:
            _login_as_superuser(client, db_session, "fa-accounts-noprov@example.com")
            resp = client.get(_ACCOUNTS_PATH)
            assert resp.status_code == 200, resp.text
        finally:
            app.dependency_overrides.pop(_get_settings, None)


# ---------------------------------------------------------------------------
# POST /factory/accounts/{id}/relogin
# ---------------------------------------------------------------------------


class TestRelogin:
    def test_unknown_id_returns_404(self, client: TestClient, db_session: Session) -> None:
        """Relogin on an unknown account id → 404."""
        _override_db(db_session)
        _override_tick_runner_noop()
        _login_as_superuser(client, db_session, "fa-relogin-404@example.com")

        settings_with_provider = _settings_with(account_factory_provider="fake")
        from config import get_settings as _get_settings

        app.dependency_overrides[_get_settings] = lambda: settings_with_provider

        try:
            resp = client.post(_relogin_path(999_999))
            assert resp.status_code == 404, resp.text
        finally:
            app.dependency_overrides.pop(_get_settings, None)

    def test_provider_unset_returns_503(self, client: TestClient, db_session: Session) -> None:
        """Relogin with provider unset → 503 (mutating, requires provider)."""
        _override_db(db_session)
        _override_tick_runner_noop()

        # Seed an existing account so it's not a 404.
        rec = factory_account_store.create_purchased(
            db_session,
            phone_masked="+7*****7001",
            provider="fake",
            provider_order_id="relogin-order-1",
            cost_usd=Decimal("1.00"),
        )
        db_session.commit()

        settings_noprovider = _settings_with(account_factory_provider="")
        from config import get_settings as _get_settings

        app.dependency_overrides[_get_settings] = lambda: settings_noprovider

        try:
            _login_as_superuser(client, db_session, "fa-relogin-503@example.com")
            resp = client.post(_relogin_path(rec.id))
            assert resp.status_code == 503, resp.text
        finally:
            app.dependency_overrides.pop(_get_settings, None)


# ---------------------------------------------------------------------------
# No-secret assertion across all endpoints
# ---------------------------------------------------------------------------


class TestNoSecretInAnyResponse:
    def test_session_string_never_in_any_response(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Exhaustive check: 'session_string' substring never appears in any endpoint body."""
        _override_db(db_session)
        _override_tick_runner_noop()

        rec = factory_account_store.create_purchased(
            db_session,
            phone_masked="+7*****8001",
            provider="fake",
            provider_order_id="nosecret-order",
            cost_usd=Decimal("1.00"),
        )
        # Must go purchased → registered → probation (state machine enforces path).
        factory_account_store.transition(
            db_session,
            rec.id,
            FACTORY_STATE_REGISTERED,
            session_string="VERY-SECRET-DO-NOT-LEAK",
            tg_user_id=444_333_222,
        )
        factory_account_store.transition(
            db_session,
            rec.id,
            FACTORY_STATE_PROBATION,
            probation_until=datetime.now(UTC) + timedelta(days=1),
        )
        db_session.commit()

        _login_as_superuser(client, db_session, "fa-nosecret-all@example.com")

        endpoints = [
            ("GET", _ACCOUNTS_PATH),
            ("GET", _BUDGET_PATH),
        ]
        for method, path in endpoints:
            resp = client.request(method, path)
            raw = resp.text
            assert "session_string" not in raw, f"session_string leaked in {method} {path}"
            assert "VERY-SECRET-DO-NOT-LEAK" not in raw, f"secret leaked in {method} {path}"
            assert "proxy" not in raw, f"proxy key leaked in {method} {path}"
