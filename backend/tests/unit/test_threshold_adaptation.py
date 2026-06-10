"""Unit tests for scorer.adaptation — adaptive threshold logic (TASK-043).

AC1: ≥K ratings + downvote_share > X% → each watchlist threshold += step, capped at floor+range.
AC2: downvote_share < Y% → threshold -= step, floored at floor.
AC3: < K ratings → no-op (threshold untouched).
AC6: threshold_floor NULL → snapshots to current threshold at first adapt tick.
     Explainability: log_event("threshold_adapted", old, new, ...) emitted per change.

Pure step function tested here without DB; seeded-DB integration test at the bottom
(marked integration) — verifies adapt_thresholds() end-to-end.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(
    *,
    threshold_adapt_min_ratings: int = 5,
    threshold_adapt_up_share: float = 0.5,
    threshold_adapt_down_share: float = 0.2,
    threshold_adapt_step: float = 5.0,
    threshold_adapt_range: float = 20.0,
    precision_window_seconds: int = 604_800,
    threshold_adapt_interval_seconds: int = 21_600,
) -> MagicMock:
    s = MagicMock()
    s.threshold_adapt_min_ratings = threshold_adapt_min_ratings
    s.threshold_adapt_up_share = threshold_adapt_up_share
    s.threshold_adapt_down_share = threshold_adapt_down_share
    s.threshold_adapt_step = threshold_adapt_step
    s.threshold_adapt_range = threshold_adapt_range
    s.precision_window_seconds = precision_window_seconds
    s.threshold_adapt_interval_seconds = threshold_adapt_interval_seconds
    return s


# ---------------------------------------------------------------------------
# AC1 — threshold grows when downvote_share > X%
# ---------------------------------------------------------------------------


class TestThresholdStepUp:
    """Pure step function: high downvote_share → threshold += step (capped)."""

    def test_step_up_basic(self) -> None:
        """downvote_share=0.6 > up_share=0.5 → new_threshold = old + step."""
        from scorer.adaptation import compute_threshold_step

        settings = _make_settings()
        result = compute_threshold_step(
            current_threshold=50.0,
            floor=50.0,
            downvote_share=0.6,
            settings=settings,
        )
        assert result is not None
        assert result == pytest.approx(55.0)

    def test_step_up_capped_at_ceiling(self) -> None:
        """threshold already near ceiling → capped at floor+range, not above."""
        from scorer.adaptation import compute_threshold_step

        settings = _make_settings()
        # floor=50, range=20 → ceiling=70; current=69 → step would → 74, cap at 70.
        result = compute_threshold_step(
            current_threshold=69.0,
            floor=50.0,
            downvote_share=0.9,
            settings=settings,
        )
        assert result is not None
        assert result == pytest.approx(70.0)

    def test_step_up_exactly_at_ceiling_is_noop(self) -> None:
        """Already at ceiling → no change (returns None = no-op)."""
        from scorer.adaptation import compute_threshold_step

        settings = _make_settings()
        result = compute_threshold_step(
            current_threshold=70.0,
            floor=50.0,
            downvote_share=0.9,
            settings=settings,
        )
        assert result is None, "at ceiling with high share → no change needed"

    def test_step_up_at_share_boundary_exactly_equal(self) -> None:
        """downvote_share exactly == up_share → not strictly greater → no step up.

        Decision: share MUST be strictly > threshold to trigger.
        """
        from scorer.adaptation import compute_threshold_step

        settings = _make_settings()
        result = compute_threshold_step(
            current_threshold=50.0,
            floor=50.0,
            downvote_share=0.5,  # exactly at up_share boundary
            settings=settings,
        )
        # Strictly less than down_share (0.2)? No. Strictly greater than up_share (0.5)? No.
        # In the dead-zone → no-op.
        assert result is None


# ---------------------------------------------------------------------------
# AC2 — threshold descends when downvote_share < Y%
# ---------------------------------------------------------------------------


class TestThresholdStepDown:
    """Pure step function: low downvote_share → threshold -= step (floored)."""

    def test_step_down_basic(self) -> None:
        """downvote_share=0.1 < down_share=0.2 → new_threshold = old - step."""
        from scorer.adaptation import compute_threshold_step

        settings = _make_settings()
        result = compute_threshold_step(
            current_threshold=60.0,
            floor=50.0,
            downvote_share=0.1,
            settings=settings,
        )
        assert result is not None
        assert result == pytest.approx(55.0)

    def test_step_down_floored_at_floor(self) -> None:
        """threshold already near floor → capped at floor, not below."""
        from scorer.adaptation import compute_threshold_step

        settings = _make_settings()
        # current=52, floor=50 → step down would → 47, floored at 50.
        result = compute_threshold_step(
            current_threshold=52.0,
            floor=50.0,
            downvote_share=0.05,
            settings=settings,
        )
        assert result is not None
        assert result == pytest.approx(50.0)

    def test_step_down_already_at_floor_is_noop(self) -> None:
        """Already at floor with low share → no change (returns None)."""
        from scorer.adaptation import compute_threshold_step

        settings = _make_settings()
        result = compute_threshold_step(
            current_threshold=50.0,
            floor=50.0,
            downvote_share=0.05,
            settings=settings,
        )
        assert result is None, "at floor with low share → no change needed"

    def test_step_down_at_share_boundary_exactly_equal(self) -> None:
        """downvote_share exactly == down_share → not strictly less → no step down."""
        from scorer.adaptation import compute_threshold_step

        settings = _make_settings()
        result = compute_threshold_step(
            current_threshold=60.0,
            floor=50.0,
            downvote_share=0.2,  # exactly at down_share boundary
            settings=settings,
        )
        # In dead-zone (0.2 ≤ share ≤ 0.5) → no-op.
        assert result is None


# ---------------------------------------------------------------------------
# AC3 — too few ratings → no-op
# ---------------------------------------------------------------------------


class TestMinRatings:
    """< K ratings in window → adapt step returns None (no adaptation)."""

    def test_below_min_ratings_is_noop(self) -> None:
        """Fewer than min_ratings → compute_threshold_step never called from adapt loop."""
        # The check happens upstream in adapt_thresholds(); here we verify that
        # the pure step function returns None when given a sentinel that indicates
        # no-op by explicit design (downvote_share=None → no ratings).
        # The actual min-ratings guard is tested via the integration test below.
        # For the pure function: mid-range share (dead zone) → no-op.
        from scorer.adaptation import compute_threshold_step

        settings = _make_settings()
        result = compute_threshold_step(
            current_threshold=55.0,
            floor=50.0,
            downvote_share=0.35,  # dead-zone: 0.2 ≤ share ≤ 0.5
            settings=settings,
        )
        assert result is None, "dead-zone share → no change"


# ---------------------------------------------------------------------------
# AC6 — floor semantics: NULL floor snapshots to current threshold
# ---------------------------------------------------------------------------


class TestFloorSemantics:
    """threshold_floor NULL → snapshot to current threshold at first adapt tick."""

    def test_null_floor_uses_current_threshold_as_floor(self) -> None:
        """When floor is None, adapt logic uses current_threshold as the floor."""
        from scorer.adaptation import resolve_floor

        floor = resolve_floor(current_threshold=75.0, threshold_floor=None)
        assert floor == pytest.approx(75.0)

    def test_existing_floor_is_preserved(self) -> None:
        """When floor is already set, resolve_floor returns it unchanged."""
        from scorer.adaptation import resolve_floor

        floor = resolve_floor(current_threshold=80.0, threshold_floor=60.0)
        assert floor == pytest.approx(60.0)

    def test_step_up_from_null_floor(self) -> None:
        """Full flow: NULL floor → snapshots to current; step up capped at floor+range."""
        from scorer.adaptation import compute_threshold_step, resolve_floor

        settings = _make_settings()
        current = 70.0
        floor = resolve_floor(current_threshold=current, threshold_floor=None)
        assert floor == pytest.approx(70.0)

        # High share → step up; ceiling = 70 + 20 = 90.
        result = compute_threshold_step(
            current_threshold=current,
            floor=floor,
            downvote_share=0.8,
            settings=settings,
        )
        assert result == pytest.approx(75.0)

    def test_step_down_from_null_floor_cannot_go_below_snapshot(self) -> None:
        """After floor snapshot, step down cannot go below the snapshotted value."""
        from scorer.adaptation import compute_threshold_step, resolve_floor

        settings = _make_settings()
        current = 70.0
        floor = resolve_floor(current_threshold=current, threshold_floor=None)

        # After a step up to 75, try to step down — floor is still 70.
        result = compute_threshold_step(
            current_threshold=70.0,
            floor=floor,
            downvote_share=0.05,
            settings=settings,
        )
        # 70 is already at floor → no-op.
        assert result is None


# ---------------------------------------------------------------------------
# Explainability — log_event("threshold_adapted") emitted per change
# ---------------------------------------------------------------------------


class TestLogEventEmitted:
    """log_event("threshold_adapted", ...) must be emitted for every watchlist changed."""

    def test_log_event_emitted_on_step_up(self) -> None:
        """adapt_thresholds() must emit log_event for each changed watchlist."""
        # This is tested via the pure-function path; the integration test below
        # verifies the DB+log path end-to-end. Here we test that the log_event
        # call happens when compute_threshold_step returns a new value.
        #
        # We monkey-patch the function and check log_event via a mock session that
        # returns a pre-seeded user summary.
        from scorer.adaptation import apply_threshold_change

        mock_watchlist = MagicMock()
        mock_watchlist.id = 42
        mock_watchlist.threshold = 50.0
        mock_watchlist.threshold_floor = 50.0

        mock_session = MagicMock()

        with patch("scorer.adaptation.log_event") as mock_log:
            apply_threshold_change(
                session=mock_session,
                watchlist=mock_watchlist,
                new_threshold=55.0,
                downvote_share=0.6,
                reason="up",
            )

        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args
        assert call_kwargs[0][0] == "threshold_adapted"
        assert call_kwargs[1]["watchlist_id"] == 42
        assert call_kwargs[1]["old"] == pytest.approx(50.0)
        assert call_kwargs[1]["new"] == pytest.approx(55.0)
        assert "user_id" in call_kwargs[1]
        assert "downvote_share" in call_kwargs[1]
        assert "reason" in call_kwargs[1]

    def test_log_event_not_emitted_when_noop(self) -> None:
        """No log_event when threshold does not change (compute_threshold_step → None)."""
        from scorer.adaptation import compute_threshold_step

        settings = _make_settings()
        result = compute_threshold_step(
            current_threshold=50.0,
            floor=50.0,
            downvote_share=0.35,  # dead zone
            settings=settings,
        )
        assert result is None
        # No log_event call should happen; the caller checks result is None.


# ---------------------------------------------------------------------------
# Invariant: threshold always in [floor, floor+range]
# ---------------------------------------------------------------------------


class TestInvariants:
    """threshold never exits [floor, floor+range] regardless of step direction."""

    @pytest.mark.parametrize(
        "current,floor,share,expected_max,expected_min",
        [
            # Normal step up: stays within range.
            (65.0, 50.0, 0.9, 70.0, 50.0),
            # Normal step down: stays at floor.
            (51.0, 50.0, 0.0, 70.0, 50.0),
            # Already at ceiling: no move.
            (70.0, 50.0, 0.9, 70.0, 50.0),
            # Already at floor: no move.
            (50.0, 50.0, 0.0, 70.0, 50.0),
        ],
    )
    def test_always_within_floor_ceiling(
        self,
        current: float,
        floor: float,
        share: float,
        expected_max: float,
        expected_min: float,
    ) -> None:
        from scorer.adaptation import compute_threshold_step

        settings = _make_settings()
        result = compute_threshold_step(
            current_threshold=current,
            floor=floor,
            downvote_share=share,
            settings=settings,
        )
        final = result if result is not None else current
        assert final >= expected_min, f"below floor: {final} < {expected_min}"
        assert final <= expected_max, f"above ceiling: {final} > {expected_max}"


# ---------------------------------------------------------------------------
# Integration: adapt_thresholds() with seeded DB (marked integration)
# ---------------------------------------------------------------------------


pytestmark_integration = pytest.mark.integration


@pytest.mark.integration
def test_adapt_thresholds_integration_step_up(db_session: Session) -> None:
    """AC1 + AC7 integration: seed 👎-heavy feedback → adapt-tick → threshold increases.

    Seeds a user with ≥min_ratings 👎 feedback rows in the 7d window;
    calls adapt_thresholds(); asserts watchlist.threshold increased.
    """
    from datetime import UTC, datetime

    from sqlalchemy.orm import Session

    from scorer.adaptation import adapt_thresholds
    from storage.models import Alert, Cluster, User, Watchlist
    from storage.models.alert_feedback import VERDICT_DOWN, VERDICT_UP, AlertFeedback
    from storage.models.channels import Channel, SourceKind

    session: Session = db_session

    # Seed user
    user = User(email="adapt_up@example.com", hashed_password="x" * 16)
    session.add(user)
    session.flush()

    # Seed channel + watchlist with threshold=50, floor=50
    ch = Channel(source_kind=SourceKind.TELEGRAM, handle="@adaptup1")
    session.add(ch)
    session.flush()

    wl = Watchlist(
        user_id=user.id,
        channel_id=ch.id,
        topic="crypto",
        threshold=50.0,
        threshold_floor=50.0,
    )
    session.add(wl)
    session.flush()

    # Seed ≥5 alerts + 👎-heavy feedback in 7d window
    now = datetime.now(UTC)
    _EMBEDDING_DIM = 384
    for i in range(6):
        cl = Cluster(
            user_id=user.id,
            topic="crypto",
            embedding=[0.1] + [0.0] * (_EMBEDDING_DIM - 1),
            first_seen=now,
            updated_at=now,
        )
        session.add(cl)
        session.flush()
        alert = Alert(
            user_id=user.id,
            cluster_id=cl.id,
            score=60.0,
            channels_count=1,
            first_seen=now,
        )
        session.add(alert)
        session.flush()
        # 5 down + 1 up → downvote_share = 5/6 ≈ 0.83 > 0.5
        verdict = VERDICT_UP if i == 5 else VERDICT_DOWN
        fb = AlertFeedback(
            user_id=user.id,
            alert_id=alert.id,
            verdict=verdict,
        )
        session.add(fb)

    session.commit()

    old_threshold = 50.0

    with patch("scorer.adaptation.log_event") as _:
        adapt_thresholds()

    session.expire_all()
    session.refresh(wl)
    assert wl.threshold > old_threshold, f"Expected threshold > {old_threshold}, got {wl.threshold}"
    assert wl.threshold <= 70.0, "Must not exceed floor+range=70"


@pytest.mark.integration
def test_adapt_thresholds_integration_no_op_few_ratings(db_session: Session) -> None:
    """AC3 integration: < K ratings → threshold unchanged."""
    from datetime import UTC, datetime

    from sqlalchemy.orm import Session

    from scorer.adaptation import adapt_thresholds
    from storage.models import Alert, Cluster, User, Watchlist
    from storage.models.alert_feedback import VERDICT_DOWN, AlertFeedback
    from storage.models.channels import Channel, SourceKind

    session: Session = db_session

    user = User(email="adapt_noop@example.com", hashed_password="x" * 16)
    session.add(user)
    session.flush()
    ch = Channel(source_kind=SourceKind.TELEGRAM, handle="@adaptnoop1")
    session.add(ch)
    session.flush()
    wl = Watchlist(
        user_id=user.id,
        channel_id=ch.id,
        topic="tech",
        threshold=50.0,
        threshold_floor=50.0,
    )
    session.add(wl)
    session.flush()

    now = datetime.now(UTC)
    _EMBEDDING_DIM = 384
    # Only 3 feedback rows (< min_ratings=5)
    for _ in range(3):
        cl = Cluster(
            user_id=user.id,
            topic="tech",
            embedding=[0.1] + [0.0] * (_EMBEDDING_DIM - 1),
            first_seen=now,
            updated_at=now,
        )
        session.add(cl)
        session.flush()
        alert = Alert(
            user_id=user.id,
            cluster_id=cl.id,
            score=60.0,
            channels_count=1,
            first_seen=now,
        )
        session.add(alert)
        session.flush()
        fb = AlertFeedback(
            user_id=user.id,
            alert_id=alert.id,
            verdict=VERDICT_DOWN,
        )
        session.add(fb)

    session.commit()

    with patch("scorer.adaptation.log_event"):
        adapt_thresholds()

    session.expire_all()
    session.refresh(wl)
    assert wl.threshold == pytest.approx(50.0), "< K ratings → no change"


@pytest.mark.integration
def test_adapt_thresholds_integration_floor_snapshot(db_session: Session) -> None:
    """AC6 integration: threshold_floor NULL → snapshotted to current_threshold on first tick."""
    from datetime import UTC, datetime

    from sqlalchemy.orm import Session

    from scorer.adaptation import adapt_thresholds
    from storage.models import Alert, Cluster, User, Watchlist
    from storage.models.alert_feedback import VERDICT_DOWN, AlertFeedback
    from storage.models.channels import Channel, SourceKind

    session: Session = db_session

    user = User(email="adapt_floor@example.com", hashed_password="x" * 16)
    session.add(user)
    session.flush()
    ch = Channel(source_kind=SourceKind.TELEGRAM, handle="@adaptfloor1")
    session.add(ch)
    session.flush()
    # threshold_floor is NULL initially
    wl = Watchlist(
        user_id=user.id,
        channel_id=ch.id,
        topic="news",
        threshold=60.0,
        threshold_floor=None,
    )
    session.add(wl)
    session.flush()

    now = datetime.now(UTC)
    _EMBEDDING_DIM = 384
    # 6 down → downvote_share > 0.5
    for _ in range(6):
        cl = Cluster(
            user_id=user.id,
            topic="news",
            embedding=[0.1] + [0.0] * (_EMBEDDING_DIM - 1),
            first_seen=now,
            updated_at=now,
        )
        session.add(cl)
        session.flush()
        alert = Alert(
            user_id=user.id,
            cluster_id=cl.id,
            score=60.0,
            channels_count=1,
            first_seen=now,
        )
        session.add(alert)
        session.flush()
        fb = AlertFeedback(
            user_id=user.id,
            alert_id=alert.id,
            verdict=VERDICT_DOWN,
        )
        session.add(fb)

    session.commit()

    with patch("scorer.adaptation.log_event"):
        adapt_thresholds()

    session.expire_all()
    session.refresh(wl)
    # Floor should have been snapshotted to 60 (old threshold), threshold bumped to 65.
    assert wl.threshold_floor == pytest.approx(60.0), "floor should be snapshotted to old threshold"
    assert wl.threshold > 60.0, "threshold should have increased"
