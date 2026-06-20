"""TASK-134 — account-factory tick integration (real pgvector Postgres).

Drives `factory.tasks.run_factory_tick` against the live test DB with the default
`fake` provider/registrar (no network) through every AC branch:
  1. pool below target + budget available → row warming on probation with a future
     `probation_until`, budget spent ↑, phone masked.
  2. force `probation_until` into the past → promote → `pool_sessions` row `source='auto'`
     with proxy set, factory row `promoted`, NO Telethon connect.
  3. budget hard-cap (budget 0) → no purchase, spend unchanged.
  4. row still within probation → NOT promoted (gate).
  5. provider unset ("") → exact no-op (no rows).

Marker: integration. Requires live pgvector Postgres. Redis is faked in-memory.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import fakeredis
import pytest
from sqlalchemy import select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from collector.constants import POOL_HEALTH_REDIS_KEY, POOL_SOURCE_AUTO, POOL_SOURCE_MANUAL
from config import Settings, get_settings
from factory.constants import (
    FACTORY_PHONE_MASK_CHAR,
    FACTORY_STATE_BANNED,
    FACTORY_STATE_PROBATION,
    FACTORY_STATE_PROMOTED,
    FACTORY_STATE_REGISTERED,
)
from factory.errors import RegistrarBannedError
from factory.proxy.fake import FakeProxyProvider
from factory.registrar.base import RegisteredSession
from factory.registrar.fake import FAKE_TG_USER_ID
from factory.tasks import run_factory_tick
from storage import factory_account_store
from storage.factory_account_store import list_by_state, total_spent_usd
from storage.models.factory_accounts import FactoryAccount
from storage.models.pool_sessions import PoolSession

pytestmark = pytest.mark.integration

_PROXY = "socks5://user:pass@10.0.0.1:1080"
_BUDGET_HEALTH = '{"healthy": 0, "target": 3, "as_of": "2026-06-20T00:00:00+00:00"}'


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    s = factory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()
        with db_engine.begin() as conn:
            conn.execute(text("DELETE FROM factory_accounts"))
            conn.execute(text("DELETE FROM pool_sessions"))


def _settings_with(**overrides: object) -> Settings:
    """A real Settings clone with factory overrides (keeps DB/auth env from the base)."""
    base = get_settings()
    return base.model_copy(update=overrides)


def _fake_redis_with_health(payload: str | None = _BUDGET_HEALTH) -> fakeredis.FakeRedis:
    redis = fakeredis.FakeRedis(decode_responses=True)
    if payload is not None:
        redis.set(POOL_HEALTH_REDIS_KEY, payload)
    return redis


def test_buy_registers_and_holds_on_probation(db_engine: Engine, session: Session) -> None:
    redis = _fake_redis_with_health()
    settings = _settings_with(
        account_factory_provider="fake",
        account_factory_budget_usd=Decimal("10"),
        account_factory_price_usd=Decimal("1"),
        account_factory_proxy_pool=_PROXY,
    )
    before = total_spent_usd(session)

    run_factory_tick(redis, settings=settings)

    session.expire_all()
    rows = list_by_state(session, FACTORY_STATE_PROBATION)
    assert len(rows) == 1
    row = rows[0]
    assert row.probation_until is not None
    assert row.probation_until > datetime.now(UTC)
    assert FACTORY_PHONE_MASK_CHAR in row.phone_masked
    assert total_spent_usd(session) == before + Decimal("1")


def test_promote_when_probation_elapsed(db_engine: Engine, session: Session) -> None:
    redis = _fake_redis_with_health()
    settings = _settings_with(
        account_factory_provider="fake",
        account_factory_budget_usd=Decimal("10"),
        account_factory_price_usd=Decimal("1"),
        account_factory_proxy_pool=_PROXY,
    )
    # Tick 1: buy → probation.
    run_factory_tick(redis, settings=settings)
    # Force probation_until into the past so the gate opens.
    with db_engine.begin() as conn:
        conn.execute(
            update(FactoryAccount).values(probation_until=datetime.now(UTC) - timedelta(days=1))
        )
    # Tick 2: promote.
    run_factory_tick(redis, settings=settings)

    session.expire_all()
    promoted = list_by_state(session, FACTORY_STATE_PROMOTED)
    assert len(promoted) == 1

    pool_row = session.scalars(
        select(PoolSession).where(PoolSession.tg_user_id == FAKE_TG_USER_ID)
    ).one()
    assert pool_row.source == POOL_SOURCE_AUTO
    assert pool_row.proxy == _PROXY
    assert pool_row.revoked_at is None


def test_budget_hard_cap_blocks_purchase(db_engine: Engine, session: Session) -> None:
    redis = _fake_redis_with_health()
    settings = _settings_with(
        account_factory_provider="fake",
        account_factory_budget_usd=Decimal("0"),
        account_factory_price_usd=Decimal("1"),
        account_factory_proxy_pool=_PROXY,
    )
    before = total_spent_usd(session)

    run_factory_tick(redis, settings=settings)

    session.expire_all()
    assert session.scalar(select(FactoryAccount.id)) is None
    assert total_spent_usd(session) == before


def test_probation_gate_blocks_premature_promote(db_engine: Engine, session: Session) -> None:
    redis = _fake_redis_with_health()
    settings = _settings_with(
        account_factory_provider="fake",
        account_factory_budget_usd=Decimal("10"),
        account_factory_price_usd=Decimal("1"),
        account_factory_proxy_pool=_PROXY,
    )
    # Tick 1: buy → probation (future probation_until). Pool stays below target.
    run_factory_tick(redis, settings=settings)
    # Tick 2 WITHOUT forcing the gate: the row is still within probation.
    run_factory_tick(redis, settings=settings)

    session.expire_all()
    assert len(list_by_state(session, FACTORY_STATE_PROMOTED)) == 0
    # Still warming on probation; no pool row was created.
    assert len(list_by_state(session, FACTORY_STATE_PROBATION)) >= 1
    assert session.scalar(select(PoolSession.id)) is None


def test_provider_unset_is_noop(db_engine: Engine, session: Session) -> None:
    redis = _fake_redis_with_health()
    settings = _settings_with(
        account_factory_provider="",
        account_factory_budget_usd=Decimal("10"),
        account_factory_price_usd=Decimal("1"),
        account_factory_proxy_pool=_PROXY,
    )

    run_factory_tick(redis, settings=settings)

    session.expire_all()
    assert session.scalar(select(FactoryAccount.id)) is None
    assert session.scalar(select(PoolSession.id)) is None


_FAKE_PROXY_URI = "socks5://fake-user:fake-pass@127.0.0.1:1080"
_FAKE_LEASE_PREFIX = "fake-proxy-"


def test_dynamic_proxy_buy_persists_lease_and_promotes(
    db_engine: Engine, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Provider set → allocate per-buy, persist lease + uri, carry proxy to the pool row."""
    proxy_provider = FakeProxyProvider()
    monkeypatch.setattr("factory.tasks.get_proxy_provider", lambda settings: proxy_provider)

    redis = _fake_redis_with_health()
    settings = _settings_with(
        account_factory_provider="fake",
        account_factory_proxy_provider="fake",
        account_factory_budget_usd=Decimal("10"),
        account_factory_price_usd=Decimal("1"),
        account_factory_proxy_price_usd=Decimal("0.50"),
        account_factory_country="DE",
        # A static pool is configured but MUST be ignored when a provider is set.
        account_factory_proxy_pool=_PROXY,
    )
    before = total_spent_usd(session)

    # Tick 1: buy → allocate dynamic proxy → probation.
    run_factory_tick(redis, settings=settings)
    session.expire_all()
    rows = list_by_state(session, FACTORY_STATE_PROBATION)
    assert len(rows) == 1
    row = rows[0]
    assert row.proxy == _FAKE_PROXY_URI  # dynamic lease uri, NOT the static pool entry
    assert row.proxy_lease_id is not None
    assert row.proxy_lease_id.startswith(_FAKE_LEASE_PREFIX)
    # cost = number ($1) + proxy ($0.50); a sticky lease is NOT released on success.
    assert total_spent_usd(session) == before + Decimal("1.50")
    assert proxy_provider.released_ids == set()

    # Force the gate open + promote: the dynamic proxy is carried onto the pool row.
    with db_engine.begin() as conn:
        conn.execute(
            update(FactoryAccount).values(probation_until=datetime.now(UTC) - timedelta(days=1))
        )
    run_factory_tick(redis, settings=settings)
    session.expire_all()
    assert len(list_by_state(session, FACTORY_STATE_PROMOTED)) == 1
    pool_row = session.scalars(
        select(PoolSession).where(PoolSession.tg_user_id == FAKE_TG_USER_ID)
    ).one()
    assert pool_row.source == POOL_SOURCE_AUTO
    assert pool_row.proxy == _FAKE_PROXY_URI
    # Promotion is sticky-for-life: the proxy is NOT released.
    assert proxy_provider.released_ids == set()


def test_dynamic_proxy_released_on_registration_failure(
    db_engine: Engine, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Registration rejects → number cancelled AND the leased proxy released once."""
    proxy_provider = FakeProxyProvider()
    monkeypatch.setattr("factory.tasks.get_proxy_provider", lambda settings: proxy_provider)

    class _BannedRegistrar:
        async def register(self, *, phone, code_cb, proxy=None):  # type: ignore[no-untyped-def]
            await code_cb()
            raise RegistrarBannedError("telegram banned this phone number")

    monkeypatch.setattr("factory.tasks.get_registrar", lambda settings: _BannedRegistrar())

    redis = _fake_redis_with_health()
    settings = _settings_with(
        account_factory_provider="fake",
        account_factory_proxy_provider="fake",
        account_factory_budget_usd=Decimal("10"),
        account_factory_price_usd=Decimal("1"),
        account_factory_proxy_price_usd=Decimal("0.50"),
    )

    # `register` raising propagates out of `_provision` (the Celery wrapper suppresses it
    # in prod); the off-ramp INSIDE `_provision` must have released the lease + cancelled
    # the number BEFORE re-raising, so neither cost leaks.
    with pytest.raises(RegistrarBannedError):
        run_factory_tick(redis, settings=settings)

    session.expire_all()
    # No probation row, no banned row (the failure happens before any row is persisted).
    assert len(list_by_state(session, FACTORY_STATE_PROBATION)) == 0
    assert len(list_by_state(session, FACTORY_STATE_BANNED)) == 0
    assert len(proxy_provider.released_ids) == 1


def test_dynamic_proxy_release_best_effort_records_banned(
    db_engine: Engine, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A banned-on-transition off-ramp releases the lease + records the row banned."""
    proxy_provider = FakeProxyProvider()
    monkeypatch.setattr("factory.tasks.get_proxy_provider", lambda settings: proxy_provider)

    class _BannedTransitionRegistrar:
        # Registration SUCCEEDS, but the store-transition will reject it as banned below.
        async def register(self, *, phone, code_cb, proxy=None):  # type: ignore[no-untyped-def]
            await code_cb()
            return RegisteredSession(session_string="1Aok", tg_user_id=FAKE_TG_USER_ID)

    monkeypatch.setattr(
        "factory.tasks.get_registrar", lambda settings: _BannedTransitionRegistrar()
    )

    # Make ONLY the `registered` transition raise banned; the subsequent `banned`
    # transition must run through to mark the row terminal.
    real_transition = factory_account_store.transition

    def _transition(sess, account_id, to_state, **kwargs):  # type: ignore[no-untyped-def]
        if to_state == FACTORY_STATE_REGISTERED:
            raise RegistrarBannedError("flagged on transition")
        return real_transition(sess, account_id, to_state, **kwargs)

    monkeypatch.setattr("factory.tasks.factory_account_store.transition", _transition)

    redis = _fake_redis_with_health()
    settings = _settings_with(
        account_factory_provider="fake",
        account_factory_proxy_provider="fake",
        account_factory_budget_usd=Decimal("10"),
        account_factory_price_usd=Decimal("1"),
        account_factory_proxy_price_usd=Decimal("0.50"),
    )

    run_factory_tick(redis, settings=settings)

    session.expire_all()
    assert len(list_by_state(session, FACTORY_STATE_BANNED)) == 1
    # The defensive banned off-ramp released the held lease (best-effort).
    assert len(proxy_provider.released_ids) == 1


def test_manual_source_unaffected(db_engine: Engine, session: Session) -> None:
    """A manually-added pool row keeps source='manual' (no regression — AC6)."""
    from storage.pool_session_store import upsert_revive_or_add

    upsert_revive_or_add(
        session,
        tg_user_id=555_000_111,
        session_string="manual-session-string",
        display_label="manual-label",
        pool_max=20,
    )
    session.commit()
    row = session.scalars(select(PoolSession).where(PoolSession.tg_user_id == 555_000_111)).one()
    assert row.source == POOL_SOURCE_MANUAL
