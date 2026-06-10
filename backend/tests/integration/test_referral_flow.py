"""Referral program integration tests (TASK-046, marker: integration).

AC1 — register with valid ref → referred_by set; invalid ref → register OK + NULL.
AC2 — IPN finished for referred user's FIRST payment → referral_rewards row
       (pending, amount=10.0); second payment → no new reward; replay → no new reward.
AC3 — GET /referral/me: lazy code generation, stable across calls, share link, own rewards.
AC4 — operator script marks paid → visible in /referral/me.
CRITICAL-A — IPN race: reward INSERT raises IntegrityError (duplicate pre-seeded) →
       200, payment processed, plan activated, exactly 1 reward, no 500.
CRITICAL-B — IPN hook failure (RuntimeError in reward creation) →
       200, payment processed/activated, no reward, no 500.
HIGH — is_first_payment_for_referral: 3rd payment (2 prior processed rows) must not raise.

IPN signing follows test_billing_ipn_route.py (HMAC-SHA512 over sorted-key compact JSON).
"""

import hashlib
import hmac
import json
from collections.abc import Iterator
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from api.main import app
from billing.deps import get_db_session, get_ipn_gateway
from billing.gateway.nowpayments import NowPaymentsGateway
from storage.models.referral_rewards import ReferralReward
from storage.models.subscriptions import BillingPayment
from storage.models.users import User

pytestmark = pytest.mark.integration

_IPN_SECRET = "integration-ipn-secret"
_SIG_HEADER = "x-nowpayments-sig"


def _sign(body: dict[str, object]) -> tuple[bytes, str]:
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(_IPN_SECRET.encode("utf-8"), raw, hashlib.sha512).hexdigest()
    return raw, sig


@pytest.fixture
def db_session_ref(db_engine: Engine) -> Iterator[Session]:
    """Session that truncates all tables on teardown (isolation)."""
    factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        with db_engine.begin() as conn:
            from storage.models import Base

            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())


@pytest.fixture
def referrer(db_session_ref: Session) -> User:
    """Referrer user with a ref_code already set."""
    u = User(email="referrer@example.com", hashed_password="x" * 16)
    db_session_ref.add(u)
    db_session_ref.flush()
    # Give them a ref code directly
    u.ref_code = "TESTCODE1"
    db_session_ref.flush()
    return u


@pytest.fixture
def referred_user(db_session_ref: Session, referrer: User) -> User:
    """Referred user with referred_by set to referrer.id."""
    u = User(
        email="referred@example.com",
        hashed_password="x" * 16,
        referred_by=referrer.id,
    )
    db_session_ref.add(u)
    db_session_ref.flush()
    return u


@pytest.fixture
def referred_invoice(db_session_ref: Session, referred_user: User) -> BillingPayment:
    payment = BillingPayment(
        user_id=referred_user.id,
        order_id="order-ref-1",
        payment_id=None,
        plan="pro",
        period="month",
        amount=Decimal("19"),
        currency="usd",
        status="pending",
    )
    db_session_ref.add(payment)
    db_session_ref.flush()
    return payment


@pytest.fixture
def second_invoice(db_session_ref: Session, referred_user: User) -> BillingPayment:
    payment = BillingPayment(
        user_id=referred_user.id,
        order_id="order-ref-2",
        payment_id=None,
        plan="pro",
        period="month",
        amount=Decimal("19"),
        currency="usd",
        status="pending",
    )
    db_session_ref.add(payment)
    db_session_ref.flush()
    return payment


@pytest.fixture
def ipn_client(db_session_ref: Session) -> Iterator[TestClient]:
    def _session_override() -> Iterator[Session]:
        yield db_session_ref

    gateway = NowPaymentsGateway(api_key="", ipn_secret=_IPN_SECRET, base_url="http://np")
    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_ipn_gateway] = lambda: gateway
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_ipn_gateway, None)


@pytest.fixture
def api_client(db_session_ref: Session) -> Iterator[TestClient]:
    """TestClient wired to db_session_ref for referral/me endpoint."""

    def _session_override() -> Iterator[Session]:
        yield db_session_ref

    app.dependency_overrides[get_db_session] = _session_override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db_session, None)


# ---------------------------------------------------------------------------
# AC1: Binding at registration
# ---------------------------------------------------------------------------


def test_register_with_valid_ref_sets_referred_by(db_session_ref: Session, referrer: User) -> None:
    """AC1: registering with a valid ref_code sets referred_by on the new user."""
    from referral.service import resolve_referrer_id

    referred_by = resolve_referrer_id(db_session_ref, ref_code="TESTCODE1")
    assert referred_by == referrer.id


def test_register_with_invalid_ref_returns_none(db_session_ref: Session) -> None:
    """AC1: registering with an unknown ref_code returns None (registration must pass)."""
    from referral.service import resolve_referrer_id

    referred_by = resolve_referrer_id(db_session_ref, ref_code="DOESNOTEXIST")
    assert referred_by is None


def test_register_with_own_code_returns_none(db_session_ref: Session, referrer: User) -> None:
    """AC1: registering with own code returns None (self-referral blocked)."""
    from referral.service import resolve_referrer_id

    referred_by = resolve_referrer_id(
        db_session_ref, ref_code="TESTCODE1", exclude_user_id=referrer.id
    )
    assert referred_by is None


# ---------------------------------------------------------------------------
# AC2: Reward on first payment
# ---------------------------------------------------------------------------


def test_first_ipn_creates_referral_reward(
    ipn_client: TestClient,
    db_session_ref: Session,
    referred_user: User,
    referrer: User,
    referred_invoice: BillingPayment,
) -> None:
    """AC2: finished IPN for a referred user's first payment → referral_rewards row."""
    body = {
        "payment_id": "np-ref-pay-1",
        "order_id": "order-ref-1",
        "payment_status": "finished",
        "price_amount": "19",
        "price_currency": "usd",
    }
    raw, sig = _sign(body)
    resp = ipn_client.post("/billing/ipn", content=raw, headers={_SIG_HEADER: sig})
    assert resp.status_code == 200, resp.text

    db_session_ref.expire_all()
    reward = db_session_ref.scalars(
        select(ReferralReward).where(ReferralReward.referred_user_id == referred_user.id)
    ).one_or_none()
    assert reward is not None
    assert reward.referrer_id == referrer.id
    assert float(reward.amount_usdt) == 10.0
    assert reward.status == "pending"
    assert reward.paid_at is None


def test_second_payment_no_new_reward(
    ipn_client: TestClient,
    db_session_ref: Session,
    referred_user: User,
    referrer: User,
    referred_invoice: BillingPayment,
    second_invoice: BillingPayment,
) -> None:
    """AC2: second payment for a referred user does NOT create another reward."""
    # First payment
    body1 = {
        "payment_id": "np-ref-pay-2a",
        "order_id": "order-ref-1",
        "payment_status": "finished",
        "price_amount": "19",
        "price_currency": "usd",
    }
    raw1, sig1 = _sign(body1)
    resp1 = ipn_client.post("/billing/ipn", content=raw1, headers={_SIG_HEADER: sig1})
    assert resp1.status_code == 200

    # Second payment (different invoice, different payment_id)
    body2 = {
        "payment_id": "np-ref-pay-2b",
        "order_id": "order-ref-2",
        "payment_status": "finished",
        "price_amount": "19",
        "price_currency": "usd",
    }
    raw2, sig2 = _sign(body2)
    resp2 = ipn_client.post("/billing/ipn", content=raw2, headers={_SIG_HEADER: sig2})
    assert resp2.status_code == 200

    db_session_ref.expire_all()
    count = len(
        db_session_ref.scalars(
            select(ReferralReward).where(ReferralReward.referred_user_id == referred_user.id)
        ).all()
    )
    assert count == 1, "Second payment must not produce a new reward row"


def test_replay_same_ipn_no_duplicate_reward(
    ipn_client: TestClient,
    db_session_ref: Session,
    referred_user: User,
    referred_invoice: BillingPayment,
) -> None:
    """AC2: replaying the same IPN does not create duplicate reward (idempotent)."""
    body = {
        "payment_id": "np-ref-pay-3",
        "order_id": "order-ref-1",
        "payment_status": "finished",
        "price_amount": "19",
        "price_currency": "usd",
    }
    raw, sig = _sign(body)
    resp1 = ipn_client.post("/billing/ipn", content=raw, headers={_SIG_HEADER: sig})
    assert resp1.status_code == 200
    # Replay
    resp2 = ipn_client.post("/billing/ipn", content=raw, headers={_SIG_HEADER: sig})
    assert resp2.status_code == 200

    db_session_ref.expire_all()
    count = len(
        db_session_ref.scalars(
            select(ReferralReward).where(ReferralReward.referred_user_id == referred_user.id)
        ).all()
    )
    assert count == 1, "Replayed IPN must not create a second reward row"


# ---------------------------------------------------------------------------
# AC3: GET /referral/me — lazy code generation, stability, scope
# ---------------------------------------------------------------------------


def test_referral_me_generates_code_lazily(
    db_session_ref: Session,
    referrer: User,
) -> None:
    """AC3: GET /referral/me triggers lazy code generation via service."""
    from referral.service import get_or_create_ref_code

    # referrer already has a code from the fixture
    code1 = get_or_create_ref_code(db_session_ref, user=referrer)
    code2 = get_or_create_ref_code(db_session_ref, user=referrer)
    assert code1 == code2, "Code must be stable across calls"
    assert len(code1) >= 8


def test_referral_me_generates_new_code_when_none(db_session_ref: Session) -> None:
    """AC3: user with no ref_code gets one created on first get_or_create_ref_code call."""
    from referral.service import get_or_create_ref_code

    user = User(email="newuser@example.com", hashed_password="x" * 16)
    db_session_ref.add(user)
    db_session_ref.flush()
    assert user.ref_code is None

    code = get_or_create_ref_code(db_session_ref, user=user)
    db_session_ref.flush()
    assert code is not None
    assert len(code) >= 8
    assert user.ref_code == code


# ---------------------------------------------------------------------------
# AC4: Operator marks reward as paid
# ---------------------------------------------------------------------------


def test_operator_mark_paid_changes_status(db_session_ref: Session, referrer: User) -> None:
    """AC4: mark_reward_paid sets status=paid and paid_at on the reward."""
    from referral.service import mark_reward_paid

    reward = ReferralReward(
        referrer_id=referrer.id,
        referred_user_id=None,  # nullable — simulates a GDPR-deleted referred user
        payment_id=None,
        amount_usdt=10.0,
        status="pending",
    )
    db_session_ref.add(reward)
    db_session_ref.flush()
    db_session_ref.refresh(reward)
    assert reward.id is not None

    mark_reward_paid(db_session_ref, reward_id=reward.id)
    db_session_ref.flush()
    db_session_ref.refresh(reward)

    assert reward.status == "paid"
    assert reward.paid_at is not None


# ---------------------------------------------------------------------------
# HTTP-path registration tests: referrer_code field (TASK-046 G2 bug fix).
#
# These tests exercise the FULL HTTP path via POST /auth/register using
# TestClient.  They catch two related bugs that existed when the payload
# field was named 'ref_code' (same as the User ORM column):
#
#   Bug A — UniqueViolation / 500: fastapi-users create_update_dict() passes
#     the payload dict directly to User(**kwargs), so ref_code='TESTCODE1'
#     lands in the INSERT, colliding with the referrer's UNIQUE ref_code.
#
#   Bug B — ref_code pollution: unknown codes like 'NOPE' end up as the new
#     user's own ref_code column value (they have no referrer, but their
#     ref_code gets set to the garbage string).
#
# Fix: rename the payload field to 'referrer_code' (no ORM column collision)
# and override create_update_dict() in UserCreate to exclude it from the
# INSERT dict entirely.  _bind_referral reads 'referrer_code' from the body.
# ---------------------------------------------------------------------------


@pytest.fixture
def register_client(db_engine: Engine) -> Iterator[TestClient]:
    """TestClient that wires NO dependency overrides — uses the real async
    session path so the fastapi-users SQLAlchemy adapter runs end-to-end."""
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def _register(
    client: TestClient, email: str, password: str = "Passw0rd!", **extra: object
) -> httpx.Response:
    """POST /auth/register and return the raw response."""
    payload: dict[str, object] = {"email": email, "password": password}
    payload.update(extra)
    return client.post("/auth/register", json=payload)


def _db_user(db_engine: Engine, email: str) -> User | None:
    """Fetch a user by email using a fresh sync session."""
    from sqlalchemy.orm import sessionmaker as sm

    factory = sm(bind=db_engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        # .unique() required: User has a joined eager-load (oauth_accounts).
        return session.scalars(select(User).where(User.email == email)).unique().one_or_none()


def test_http_register_with_valid_referrer_code(
    register_client: TestClient,
    db_engine: Engine,
    db_session_ref: Session,
    referrer: User,
) -> None:
    """HTTP AC1a: POST /auth/register with a valid referrer_code →
    201, new user.referred_by == referrer.id, new user.ref_code IS NULL.

    RED failure (before fix): the field was 'ref_code' — fastapi-users passed it
    straight into the INSERT as user.ref_code='TESTCODE1', colliding with the
    referrer's UNIQUE ref_code → 500 UniqueViolation. After fix (renamed to
    'referrer_code', excluded from insert): referred_by is set by _bind_referral,
    ref_code stays NULL.
    """
    db_session_ref.commit()  # make the referrer visible to the async session

    resp = _register(register_client, "newuser_valid@example.com", referrer_code="TESTCODE1")
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

    user = _db_user(db_engine, "newuser_valid@example.com")
    assert user is not None, "New user must exist in DB"
    assert user.referred_by == referrer.id, (
        f"referred_by must be {referrer.id}, got {user.referred_by}"
    )
    assert user.ref_code is None, (
        f"ref_code must be NULL (not polluted with referrer code), got {user.ref_code!r}"
    )


def test_http_register_with_unknown_referrer_code(
    register_client: TestClient,
    db_engine: Engine,
    db_session_ref: Session,
) -> None:
    """HTTP AC1b: POST /auth/register with unknown code 'NOPE' →
    201, referred_by NULL, ref_code NULL (no pollution).

    RED failure (before fix, with old 'ref_code' field): 'NOPE' was passed into
    the INSERT as user.ref_code='NOPE', polluting the new user's ref_code column.
    After fix: 'referrer_code' is excluded from the insert dict entirely, so
    user.ref_code stays NULL.
    """
    db_session_ref.commit()

    resp = _register(register_client, "newuser_unknown@example.com", referrer_code="NOPE")
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

    user = _db_user(db_engine, "newuser_unknown@example.com")
    assert user is not None
    assert user.referred_by is None, f"referred_by must be NULL, got {user.referred_by}"
    assert user.ref_code is None, (
        f"ref_code must be NULL (must not be polluted with 'NOPE'), got {user.ref_code!r}"
    )


def test_http_register_second_referred_user_no_unique_violation(
    register_client: TestClient,
    db_engine: Engine,
    db_session_ref: Session,
    referrer: User,
) -> None:
    """HTTP AC1c: two different users register with the same referrer code →
    both 201, no UNIQUE violation, both have referred_by == referrer.id.

    RED failure (before fix, with old 'ref_code' field): first insert sets
    user.ref_code='TESTCODE1', second insert hits the UNIQUE constraint → 500.
    After fix: 'referrer_code' excluded from insert — no collision.
    """
    db_session_ref.commit()

    resp1 = _register(register_client, "referred_b1@example.com", referrer_code="TESTCODE1")
    assert resp1.status_code == 201, (
        f"First referred register failed: {resp1.status_code}: {resp1.text}"
    )

    resp2 = _register(register_client, "referred_b2@example.com", referrer_code="TESTCODE1")
    assert resp2.status_code == 201, (
        f"Second referred register failed (UniqueViolation?): {resp2.status_code}: {resp2.text}"
    )

    user1 = _db_user(db_engine, "referred_b1@example.com")
    user2 = _db_user(db_engine, "referred_b2@example.com")
    assert user1 is not None and user2 is not None
    assert user1.referred_by == referrer.id, f"user1.referred_by must be {referrer.id}"
    assert user2.referred_by == referrer.id, f"user2.referred_by must be {referrer.id}"
    assert user1.ref_code is None, f"user1.ref_code must be NULL, got {user1.ref_code!r}"
    assert user2.ref_code is None, f"user2.ref_code must be NULL, got {user2.ref_code!r}"


# ---------------------------------------------------------------------------
# CRITICAL-A: IPN race — reward INSERT raises IntegrityError (pre-seeded duplicate)
#   BEFORE fix: session.rollback() inside create_referral_reward_if_first_payment
#   rolls back the ENTIRE IPN transaction → plan NOT activated, payment NOT marked
#   processed, and the subsequent session.flush() raises → 500.
#   AFTER fix: begin_nested() (SAVEPOINT) isolates the reward INSERT; outer tx
#   is preserved → 200, plan activated, exactly one reward, no 500.
# ---------------------------------------------------------------------------


def test_ipn_integrity_error_in_reward_does_not_rollback_payment(
    ipn_client: TestClient,
    db_session_ref: Session,
    referred_user: User,
    referrer: User,
    referred_invoice: BillingPayment,
) -> None:
    """CRITICAL-A: race simulation — reward INSERT hits UNIQUE constraint (IntegrityError).
    The outer IPN transaction must survive. Expect: 200, payment.status=='processed',
    exactly 1 reward row (the pre-seeded one), no 500.

    Race scenario: two concurrent IPN calls both pass is_first_payment_for_referral
    (no reward row yet at the time of the check), then both attempt INSERT.  One wins;
    the other hits IntegrityError and calls session.rollback() — THE BUG.

    We simulate this by:
      (a) pre-seeding a reward row so the DB has a UNIQUE violation waiting, then
      (b) patching _referral_reward_exists to return False (bypassing the pre-check,
          matching the race window where the check ran before the competitor committed).

    BEFORE fix: session.rollback() rolls back the outer tx → payment stays 'pending'.
    AFTER fix:  begin_nested() isolates the INSERT; outer tx survives → 'processed'.
    """
    # Pre-seed a reward row to guarantee the INSERT will collide.
    existing_reward = ReferralReward(
        referrer_id=referrer.id,
        referred_user_id=referred_user.id,
        payment_id=None,
        amount_usdt=10.0,
        status="pending",
    )
    db_session_ref.add(existing_reward)
    db_session_ref.commit()

    body = {
        "payment_id": "np-critical-a-1",
        "order_id": "order-ref-1",
        "payment_status": "finished",
        "price_amount": "19",
        "price_currency": "usd",
    }
    raw, sig = _sign(body)

    # Bypass _referral_reward_exists (simulates the race window) so the INSERT runs
    # and hits the UNIQUE constraint — this is the actual trigger for the bug.
    with patch("referral.service._referral_reward_exists", return_value=False):
        resp = ipn_client.post("/billing/ipn", content=raw, headers={_SIG_HEADER: sig})

    # CRITICAL: must not 500; outer IPN transaction must survive.
    assert resp.status_code == 200, (
        f"IPN returned {resp.status_code} after reward IntegrityError — "
        f"session.rollback() poisoned the outer transaction. Body: {resp.text}"
    )

    db_session_ref.expire_all()
    # Payment must have been activated (status processed).
    payment = db_session_ref.scalars(
        select(BillingPayment).where(BillingPayment.order_id == "order-ref-1")
    ).one_or_none()
    assert payment is not None
    assert payment.status == "processed", (
        f"Payment.status must be 'processed' but got {payment.status!r} — "
        f"IntegrityError in reward rollback poisoned the transaction."
    )

    # Exactly one reward (the pre-seeded one, not a duplicate).
    rewards = db_session_ref.scalars(
        select(ReferralReward).where(ReferralReward.referred_user_id == referred_user.id)
    ).all()
    assert len(rewards) == 1, f"Expected exactly 1 reward, got {len(rewards)}"


# ---------------------------------------------------------------------------
# CRITICAL-B: generic hook failure (RuntimeError in reward creation)
#   BEFORE fix: RuntimeError propagates out of create_referral_reward_if_first_payment
#   (the inner except block catches IntegrityError only); the outer try/except in
#   webhook.py swallows it BUT the session is left in an aborted state (no rollback)
#   → subsequent session.flush() raises InternalError → 500.
#   AFTER fix: the entire reward block runs inside begin_nested(); any exception
#   rolls back only the savepoint and the outer session stays clean → 200.
# ---------------------------------------------------------------------------


def test_ipn_runtime_error_in_reward_hook_does_not_cause_500(
    ipn_client: TestClient,
    db_session_ref: Session,
    referred_user: User,
    referrer: User,
    referred_invoice: BillingPayment,
) -> None:
    """CRITICAL-B: a non-IntegrityError exception from session.flush() inside the reward
    block must NOT poison the outer IPN transaction.
    Expect: 200, payment processed/activated, no reward created, no 500.

    The bug: the inner except only catches IntegrityError; if session.flush() raises
    anything else (e.g., OperationalError, DataError) the outer except Exception catches
    it but the session is left with a pending rollback (SQLAlchemy PendingRollbackError).
    The subsequent session.flush() in process_ipn then raises → 500.

    We simulate this by injecting a pre-seeded reward with an invalid referrer_id (FK
    violation = IntegrityError subclass ForeignKeyViolation) bypassing the UNIQUE guard
    logic, which forces a non-UNIQUE IntegrityError that propagates past the inner handler
    and aborts the session.

    BEFORE fix: session.flush() at line 115 of webhook.py raises PendingRollbackError → 500.
    AFTER fix: begin_nested() wraps the reward block; rollback on the savepoint keeps
    the outer tx clean → 200, payment processed.
    """
    body = {
        "payment_id": "np-critical-b-1",
        "order_id": "order-ref-1",
        "payment_status": "finished",
        "price_amount": "19",
        "price_currency": "usd",
    }
    raw, sig = _sign(body)

    # Patch session.flush inside the reward service to raise OperationalError on
    # the first call (simulating a transient DB error during the reward INSERT).
    # This bypasses IntegrityError handling and leaves the session in a bad state
    # under the current code (no begin_nested → PendingRollbackError on outer flush).
    from sqlalchemy.exc import OperationalError

    original_flush = db_session_ref.flush
    # fired[0]: True once we have raised the OperationalError to prevent the
    # patch from firing again on the outer session.flush() call.
    fired = [False]

    def patched_flush(*args: object, **kwargs: object) -> None:
        if not fired[0]:
            from storage.models.referral_rewards import ReferralReward as RR

            has_reward = any(isinstance(obj, RR) for obj in db_session_ref.new)
            if has_reward:
                fired[0] = True
                raise OperationalError("simulated DB error on reward INSERT", None, None)
        return original_flush(*args, **kwargs)

    db_session_ref.flush = patched_flush  # type: ignore[method-assign]
    try:
        resp = ipn_client.post("/billing/ipn", content=raw, headers={_SIG_HEADER: sig})
    finally:
        db_session_ref.flush = original_flush  # type: ignore[method-assign]

    assert resp.status_code == 200, (
        f"IPN returned {resp.status_code} after OperationalError in reward flush — "
        f"aborted session (PendingRollbackError) not cleaned up. Body: {resp.text}"
    )

    db_session_ref.expire_all()
    # Payment must still be activated despite hook failure.
    payment = db_session_ref.scalars(
        select(BillingPayment).where(BillingPayment.order_id == "order-ref-1")
    ).one_or_none()
    assert payment is not None
    assert payment.status == "processed", (
        f"Payment.status must be 'processed' but got {payment.status!r}"
    )

    # No reward must have been created.
    rewards = db_session_ref.scalars(
        select(ReferralReward).where(ReferralReward.referred_user_id == referred_user.id)
    ).all()
    assert len(rewards) == 0, f"Expected 0 rewards after hook failure, got {len(rewards)}"


# ---------------------------------------------------------------------------
# HIGH: is_first_payment_for_referral — 3rd payment (2 prior processed rows)
#   must not raise and must not create a reward.
# ---------------------------------------------------------------------------


def test_third_payment_no_reward_no_raise(
    ipn_client: TestClient,
    db_session_ref: Session,
    referred_user: User,
    referrer: User,
    referred_invoice: BillingPayment,
    second_invoice: BillingPayment,
) -> None:
    """HIGH: third payment for a referred user → 200, no new reward, no exception.

    Two prior processed payments already exist (first two IPNs); the third payment
    must return 200 and not create a reward.  The one_or_none() → .first() change
    is validated indirectly: two prior rows means one_or_none() would raise
    MultipleResultsFound without the limit(1) fix, while .first() handles it cleanly.
    """
    # First payment activates the plan and creates the reward.
    body1 = {
        "payment_id": "np-high-3p-1",
        "order_id": "order-ref-1",
        "payment_status": "finished",
        "price_amount": "19",
        "price_currency": "usd",
    }
    raw1, sig1 = _sign(body1)
    resp1 = ipn_client.post("/billing/ipn", content=raw1, headers={_SIG_HEADER: sig1})
    assert resp1.status_code == 200, f"First IPN failed: {resp1.text}"

    # Second payment activates for the same user (new invoice = renewal).
    body2 = {
        "payment_id": "np-high-3p-2",
        "order_id": "order-ref-2",
        "payment_status": "finished",
        "price_amount": "19",
        "price_currency": "usd",
    }
    raw2, sig2 = _sign(body2)
    resp2 = ipn_client.post("/billing/ipn", content=raw2, headers={_SIG_HEADER: sig2})
    assert resp2.status_code == 200, f"Second IPN failed: {resp2.text}"

    # Add a third invoice and fire it.
    third_invoice = BillingPayment(
        user_id=referred_user.id,
        order_id="order-ref-3",
        payment_id=None,
        plan="pro",
        period="month",
        amount=Decimal("19"),
        currency="usd",
        status="pending",
    )
    db_session_ref.add(third_invoice)
    db_session_ref.commit()

    body3 = {
        "payment_id": "np-high-3p-3",
        "order_id": "order-ref-3",
        "payment_status": "finished",
        "price_amount": "19",
        "price_currency": "usd",
    }
    raw3, sig3 = _sign(body3)
    resp3 = ipn_client.post("/billing/ipn", content=raw3, headers={_SIG_HEADER: sig3})
    assert resp3.status_code == 200, (
        f"Third IPN returned {resp3.status_code} — possible MultipleResultsFound from "
        f"one_or_none() on 2 prior processed payments. Body: {resp3.text}"
    )

    db_session_ref.expire_all()
    # Reward count must still be exactly 1 (from first payment only).
    rewards = db_session_ref.scalars(
        select(ReferralReward).where(ReferralReward.referred_user_id == referred_user.id)
    ).all()
    assert len(rewards) == 1, f"Expected exactly 1 reward after 3 payments, got {len(rewards)}"
