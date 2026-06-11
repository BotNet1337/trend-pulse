"""Integration tests for GET /cases + showcase_cases fixation (TASK-045).

Markers: integration

AC4: GET /cases — public (no auth), returns only cases with mainstream_at NOT NULL,
     sorted by lead_time DESC (mainstream_at - first_seen), capped at cases_top_n_max;
     200 [] when no qualifying cases.

AC1 (integration): seeding a cluster with viral_score >= 90 + calling fix_cases()
     inserts a showcase_cases row with complete snapshot fields.

AC2 (integration): calling fix_cases() twice for the same cluster → still one row
     (idempotent on_conflict_do_nothing).

AC3 (purge-survival): after a showcase_cases row is written, deleting the source
     cluster does NOT remove the case (no FK — snapshot is self-sufficient).

Security (5.5): GET /cases response contains ONLY schema-defined fields; no extra
     internal fields leak through.

Pattern: mirrors test_trending_api.py / test_showcase_autopost.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from api.main import app
from api.watchlist.deps import get_db_session

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EMBEDDING_DIM = 384
_EMBEDDING = [0.0] * _EMBEDDING_DIM


def _seed_showcase_user(session: Session) -> int:
    """Create (or return existing) showcase system user. Returns user_id."""
    from sqlalchemy import select

    from config import get_settings
    from storage.models.users import User

    email = get_settings().showcase_user_email
    existing = session.scalar(select(User).where(User.__table__.c.email == email))
    if existing is not None:
        return existing.id
    user = User(email=email, hashed_password="x" * 16)
    session.add(user)
    session.flush()
    return user.id


def _seed_cluster_and_score(
    session: Session,
    *,
    user_id: int,
    topic: str,
    viral_score: float,
    first_seen: datetime | None = None,
) -> int:
    """Seed cluster + score. Returns cluster id."""
    from storage.models.clusters import Cluster
    from storage.models.scores import Score

    now = datetime.now(UTC)
    cluster = Cluster(
        user_id=user_id,
        topic=topic,
        embedding=_EMBEDDING,
        first_seen=first_seen or now,
        updated_at=first_seen or now,
    )
    session.add(cluster)
    session.flush()

    score = Score(
        user_id=user_id,
        cluster_id=cluster.id,
        viral_score=viral_score,
        velocity=1.0,
        engagement=1.0,
        cross_channel=0.5,
    )
    session.add(score)
    session.flush()
    return cluster.id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session_committing(db_engine: Engine) -> Iterator[Session]:
    """Session whose flushes are immediately visible to the app (shared conn)."""
    from sqlalchemy.orm import sessionmaker

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
def anon_client(db_session_committing: Session) -> Iterator[TestClient]:
    """Unauthenticated TestClient with overridden DB session (GET /cases is public)."""

    def _session_override() -> Iterator[Session]:
        yield db_session_committing

    app.dependency_overrides[get_db_session] = _session_override
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db_session, None)


# ---------------------------------------------------------------------------
# AC4 — GET /cases basics
# ---------------------------------------------------------------------------


def test_cases_no_auth_returns_200_empty_list(anon_client: TestClient) -> None:
    """AC4: GET /cases with no auth → 200 with empty list (no qualifying cases)."""
    resp = anon_client.get("/v1/cases")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    assert body["items"] == []


def test_cases_returns_only_mainstream_at_not_null(
    anon_client: TestClient,
    db_session_committing: Session,
) -> None:
    """AC4: Cases without mainstream_at are NOT returned."""
    from storage.models.showcase_cases import ShowcaseCase

    now = datetime.now(UTC)

    # Case WITH mainstream_at (should appear)
    case_with = ShowcaseCase(
        title="visible case",
        viral_score=92.0,
        first_seen=now - timedelta(hours=5),
        channels_count=1,
        mainstream_at=now - timedelta(hours=1),
        created_at=now,
    )
    # Case WITHOUT mainstream_at (should NOT appear)
    case_without = ShowcaseCase(
        title="hidden case",
        viral_score=91.0,
        first_seen=now - timedelta(hours=3),
        channels_count=1,
        mainstream_at=None,
        created_at=now,
    )
    db_session_committing.add(case_with)
    db_session_committing.add(case_without)
    db_session_committing.flush()
    db_session_committing.commit()

    resp = anon_client.get("/v1/cases")
    assert resp.status_code == 200, resp.text

    items = resp.json()["items"]
    titles = [item["title"] for item in items]
    assert "visible case" in titles, "Case with mainstream_at must appear"
    assert "hidden case" not in titles, "Case without mainstream_at must NOT appear"


def test_cases_sorted_by_lead_time_desc(
    anon_client: TestClient,
    db_session_committing: Session,
) -> None:
    """AC4: Cases sorted by (mainstream_at - first_seen) DESC (longest lead-time first)."""
    from storage.models.showcase_cases import ShowcaseCase

    now = datetime.now(UTC)

    # Case A: lead time = 10 hours
    case_a = ShowcaseCase(
        title="case A",
        viral_score=90.5,
        first_seen=now - timedelta(hours=12),
        channels_count=1,
        mainstream_at=now - timedelta(hours=2),
        created_at=now,
    )
    # Case B: lead time = 2 hours
    case_b = ShowcaseCase(
        title="case B",
        viral_score=91.0,
        first_seen=now - timedelta(hours=4),
        channels_count=1,
        mainstream_at=now - timedelta(hours=2),
        created_at=now,
    )
    # Case C: lead time = 24 hours (longest)
    case_c = ShowcaseCase(
        title="case C",
        viral_score=89.0,
        first_seen=now - timedelta(hours=26),
        channels_count=1,
        mainstream_at=now - timedelta(hours=2),
        created_at=now,
    )
    db_session_committing.add(case_a)
    db_session_committing.add(case_b)
    db_session_committing.add(case_c)
    db_session_committing.flush()
    db_session_committing.commit()

    resp = anon_client.get("/v1/cases")
    assert resp.status_code == 200, resp.text

    items = resp.json()["items"]
    assert len(items) >= 3

    # Verify descending order by lead_time_seconds
    lead_times = [item["lead_time_seconds"] for item in items]
    assert lead_times == sorted(lead_times, reverse=True), (
        f"Items not sorted DESC by lead_time_seconds: {lead_times}"
    )
    # Case C has longest lead time (≈ 24h)
    assert items[0]["title"] == "case C"


def test_cases_capped_at_top_n(
    anon_client: TestClient,
    db_session_committing: Session,
) -> None:
    """AC4: Response capped at cases_top_n_max (default 20)."""
    from config import get_settings
    from storage.models.showcase_cases import ShowcaseCase

    now = datetime.now(UTC)
    max_n = get_settings().cases_top_n_max

    # Seed max_n + 5 cases (all with mainstream_at)
    for i in range(max_n + 5):
        case = ShowcaseCase(
            title=f"case {i}",
            viral_score=float(90 + i % 5),
            first_seen=now - timedelta(hours=i + 3),
            channels_count=1,
            mainstream_at=now - timedelta(hours=1),
            created_at=now,
        )
        db_session_committing.add(case)
    db_session_committing.flush()
    db_session_committing.commit()

    resp = anon_client.get("/v1/cases")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) <= max_n, f"Expected at most {max_n} items, got {len(items)}"


def test_cases_top_n_param_over_max_returns_422(
    anon_client: TestClient,
    db_session_committing: Session,
) -> None:
    """AC4: top_n query param > cases_top_n_max → 422."""
    from config import get_settings

    max_n = get_settings().cases_top_n_max
    resp = anon_client.get("/v1/cases", params={"top_n": max_n + 1})
    assert resp.status_code == 422, resp.text


def test_cases_response_contains_only_schema_fields(
    anon_client: TestClient,
    db_session_committing: Session,
) -> None:
    """Security 5.5: response items contain ONLY defined schema fields — no extras."""
    from storage.models.showcase_cases import ShowcaseCase

    now = datetime.now(UTC)
    case = ShowcaseCase(
        title="schema test",
        viral_score=91.5,
        first_seen=now - timedelta(hours=5),
        channels_count=1,
        mainstream_at=now - timedelta(hours=1),
        created_at=now,
    )
    db_session_committing.add(case)
    db_session_committing.flush()
    db_session_committing.commit()

    resp = anon_client.get("/v1/cases")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) >= 1

    # Allowed schema fields only
    allowed_fields = {
        "title",
        "viral_score",
        "first_seen",
        "mainstream_at",
        "lead_time_seconds",
        "channels_count",
    }
    for item in items:
        extra = set(item.keys()) - allowed_fields
        assert not extra, f"Unexpected fields in /cases response: {extra}"

    # Must NOT expose internal id or raw fields
    for item in items:
        assert "id" not in item, "Internal id must not be exposed"
        assert "raw" not in item
        assert "text" not in item
        assert "content" not in item


def test_cases_lead_time_seconds_computed_correctly(
    anon_client: TestClient,
    db_session_committing: Session,
) -> None:
    """AC4: lead_time_seconds == (mainstream_at - first_seen) in seconds."""
    from storage.models.showcase_cases import ShowcaseCase

    now = datetime.now(UTC)
    first_seen = now - timedelta(hours=6)  # 6 hours ago
    mainstream_at = now - timedelta(hours=1)  # 1 hour ago
    expected_lead_secs = int((mainstream_at - first_seen).total_seconds())

    case = ShowcaseCase(
        title="lead time test",
        viral_score=92.0,
        first_seen=first_seen,
        channels_count=1,
        mainstream_at=mainstream_at,
        created_at=now,
    )
    db_session_committing.add(case)
    db_session_committing.flush()
    db_session_committing.commit()

    resp = anon_client.get("/v1/cases")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) >= 1

    lt_item = next((i for i in items if i["title"] == "lead time test"), None)
    assert lt_item is not None
    assert abs(lt_item["lead_time_seconds"] - expected_lead_secs) < 2, (
        f"lead_time_seconds mismatch: got {lt_item['lead_time_seconds']}, "
        f"expected ~{expected_lead_secs}"
    )


# ---------------------------------------------------------------------------
# AC1 (integration) — fixation inserts a row
# ---------------------------------------------------------------------------


def test_fix_cases_inserts_row_for_qualifying_cluster(
    db_session_committing: Session,
) -> None:
    """AC1: fix_cases() inserts showcase_cases row for cluster with score >= threshold."""
    from sqlalchemy import func, select

    from config import get_settings
    from showcase.cases import fix_cases
    from storage.models.showcase_cases import ShowcaseCase

    settings = get_settings()
    now = datetime.now(UTC)

    showcase_uid = _seed_showcase_user(db_session_committing)
    _seed_cluster_and_score(
        db_session_committing,
        user_id=showcase_uid,
        topic="DeFi rally big move",
        viral_score=settings.showcase_case_min_score,  # exactly at threshold
        first_seen=now - timedelta(hours=2),
    )
    db_session_committing.commit()

    fix_cases(db_session_committing, settings=settings, now=now)
    db_session_committing.commit()

    count = db_session_committing.scalar(select(func.count(ShowcaseCase.id)))
    assert count == 1, f"Expected 1 showcase_cases row, got {count}"


def test_fix_cases_does_not_insert_row_below_threshold(
    db_session_committing: Session,
) -> None:
    """AC1: fix_cases() does NOT insert row for cluster with score < threshold."""
    from sqlalchemy import func, select

    from config import get_settings
    from showcase.cases import fix_cases
    from storage.models.showcase_cases import ShowcaseCase

    settings = get_settings()
    now = datetime.now(UTC)

    showcase_uid = _seed_showcase_user(db_session_committing)
    _seed_cluster_and_score(
        db_session_committing,
        user_id=showcase_uid,
        topic="minor blip",
        viral_score=settings.showcase_case_min_score - 0.1,  # just below
        first_seen=now - timedelta(hours=2),
    )
    db_session_committing.commit()

    fix_cases(db_session_committing, settings=settings, now=now)
    db_session_committing.commit()

    count = db_session_committing.scalar(select(func.count(ShowcaseCase.id)))
    assert count == 0, f"Expected 0 showcase_cases rows, got {count}"


def test_fix_cases_snapshot_fields_are_complete(
    db_session_committing: Session,
) -> None:
    """AC1: inserted row has title, viral_score, first_seen, channels_count, created_at."""
    from sqlalchemy import select

    from config import get_settings
    from showcase.cases import fix_cases
    from storage.models.showcase_cases import ShowcaseCase

    settings = get_settings()
    now = datetime.now(UTC)
    first_seen_ts = now - timedelta(hours=3)

    showcase_uid = _seed_showcase_user(db_session_committing)
    _seed_cluster_and_score(
        db_session_committing,
        user_id=showcase_uid,
        topic="clean topic label",
        viral_score=95.0,
        first_seen=first_seen_ts,
    )
    db_session_committing.commit()

    fix_cases(db_session_committing, settings=settings, now=now)
    db_session_committing.commit()

    row = db_session_committing.scalar(select(ShowcaseCase))
    assert row is not None
    assert row.title == "clean topic label"
    assert abs(row.viral_score - 95.0) < 0.001
    assert row.channels_count >= 1
    assert row.mainstream_at is None  # filled by operator later
    assert row.created_at is not None


def test_fix_cases_title_is_sanitized(
    db_session_committing: Session,
) -> None:
    """Compliance: inserted title has no URLs or @-handles (sanitized before storage)."""
    from sqlalchemy import select

    from config import get_settings
    from showcase.cases import fix_cases
    from storage.models.showcase_cases import ShowcaseCase

    settings = get_settings()
    now = datetime.now(UTC)

    showcase_uid = _seed_showcase_user(db_session_committing)
    # Cluster topic contains raw URL and handle
    _seed_cluster_and_score(
        db_session_committing,
        user_id=showcase_uid,
        topic="big rally https://t.me/channel @spammer pump",
        viral_score=92.0,
        first_seen=now - timedelta(hours=1),
    )
    db_session_committing.commit()

    fix_cases(db_session_committing, settings=settings, now=now)
    db_session_committing.commit()

    row = db_session_committing.scalar(select(ShowcaseCase))
    assert row is not None
    assert "https://" not in row.title
    assert "t.me/" not in row.title
    assert "@spammer" not in row.title


# ---------------------------------------------------------------------------
# AC2 (integration) — idempotency
# ---------------------------------------------------------------------------


def test_fix_cases_idempotent_second_call_no_duplicate(
    db_session_committing: Session,
) -> None:
    """AC2: second call to fix_cases() with same cluster → still one row."""
    from sqlalchemy import func, select

    from config import get_settings
    from showcase.cases import fix_cases
    from storage.models.showcase_cases import ShowcaseCase

    settings = get_settings()
    now = datetime.now(UTC)

    showcase_uid = _seed_showcase_user(db_session_committing)
    _seed_cluster_and_score(
        db_session_committing,
        user_id=showcase_uid,
        topic="idempotent test",
        viral_score=91.0,
        first_seen=now - timedelta(hours=1),
    )
    db_session_committing.commit()

    fix_cases(db_session_committing, settings=settings, now=now)
    db_session_committing.commit()

    # Second tick — same cluster still qualifies
    fix_cases(db_session_committing, settings=settings, now=now + timedelta(minutes=15))
    db_session_committing.commit()

    count = db_session_committing.scalar(select(func.count(ShowcaseCase.id)))
    assert count == 1, f"Expected exactly 1 row after 2 calls, got {count}"


# ---------------------------------------------------------------------------
# AC3 — purge-survival: case survives cluster deletion
# ---------------------------------------------------------------------------


def test_case_survives_cluster_deletion(
    db_session_committing: Session,
) -> None:
    """AC3: showcase_cases row survives deletion of its source cluster (no FK).

    The retention purge in production deletes dependent rows (scores, posts)
    before deleting the cluster.  This test simulates that by deleting the
    score row first, then the cluster, and verifying the showcase_cases row
    is unaffected (no FK → survives the purge).
    """
    from sqlalchemy import func, select

    from config import get_settings
    from showcase.cases import fix_cases
    from storage.models.clusters import Cluster
    from storage.models.scores import Score
    from storage.models.showcase_cases import ShowcaseCase

    settings = get_settings()
    now = datetime.now(UTC)

    showcase_uid = _seed_showcase_user(db_session_committing)
    cluster_id = _seed_cluster_and_score(
        db_session_committing,
        user_id=showcase_uid,
        topic="purge survival test",
        viral_score=93.0,
        first_seen=now - timedelta(hours=2),
    )
    db_session_committing.commit()

    fix_cases(db_session_committing, settings=settings, now=now)
    db_session_committing.commit()

    # Confirm case row exists before purge
    count_before = db_session_committing.scalar(select(func.count(ShowcaseCase.id)))
    assert count_before == 1

    # Simulate retention purge: delete score first (FK cluster→scores), then cluster.
    # Production retention purge nulls post.text and eventually deletes dependent rows
    # before removing the cluster; we replicate that ordering here.
    score_row = db_session_committing.scalar(select(Score).where(Score.cluster_id == cluster_id))
    if score_row is not None:
        db_session_committing.delete(score_row)
        db_session_committing.flush()

    cluster_row = db_session_committing.get(Cluster, cluster_id)
    assert cluster_row is not None
    db_session_committing.delete(cluster_row)
    db_session_committing.flush()
    db_session_committing.commit()

    # showcase_cases row must still exist (no FK — snapshot is self-sufficient).
    count_after = db_session_committing.scalar(select(func.count(ShowcaseCase.id)))
    assert count_after == 1, (
        "showcase_cases row must survive cluster deletion (no FK — snapshot self-sufficient)"
    )
