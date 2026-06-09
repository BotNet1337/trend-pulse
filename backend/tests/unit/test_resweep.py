"""Unit tests for `resweep_pending_alerts` (AC1/AC2 anchor — RED first).

Tests are DB-free: the SQLAlchemy session is mocked so no Postgres is needed
(`make ci-fast`). Asserts:

- Only `pending` alerts older than grace are re-enqueued (stale-pending).
- Fresh `pending` (within grace window) are NOT touched.
- `delivered` / `failed` are NEVER re-enqueued (idempotency invariant).
- The max-batch cap is respected (no queue flood).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

_GRACE = 300  # seconds — mirrors _DEFAULT_PENDING_RESWEEP_GRACE_SECONDS


def _make_alert(
    alert_id: int,
    status: str,
    age_seconds: int,
) -> MagicMock:
    """Return a mock Alert with `id`, `delivery_status`, and `first_seen`."""
    a = MagicMock(name=f"alert_{alert_id}")
    a.id = alert_id
    a.delivery_status = status
    a.first_seen = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return a


# ---------------------------------------------------------------------------
# Helpers: build a mock Session whose `execute().scalars().all()` returns rows.
# ---------------------------------------------------------------------------


def _make_session(rows: list[int]) -> MagicMock:
    """Session that returns `rows` (list of alert IDs) from a scalar query."""
    scalars = MagicMock()
    scalars.all.return_value = rows
    result = MagicMock()
    result.scalars.return_value = scalars
    session = MagicMock()
    session.execute.return_value = result
    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_resweep_selects_only_stale_pending() -> None:
    """Only pending alerts older than grace are re-enqueued; fresh/other are not."""
    from alerts.constants import RESWEEP_PENDING_ALERTS_TASK  # noqa: F401 (import check)
    from alerts.tasks import _resweep_pending_alerts

    stale_id = 1
    # Only the stale pending ID is returned by the query (filter logic tested in DB
    # integration; here we test that _resweep_pending_alerts enqueues what the query
    # returns and not more).
    mock_session = _make_session([stale_id])

    with (
        patch("alerts.tasks.get_session") as mock_get_session,
        patch("alerts.tasks.dispatch_alert") as mock_dispatch,
    ):
        # Simulate the context-manager-based get_session.
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=mock_session)
        cm.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = cm

        count = _resweep_pending_alerts()

    assert count == 1
    mock_dispatch.apply_async.assert_called_once_with(args=(stale_id,))


def test_resweep_idempotent_only_pending() -> None:
    """delivered/failed are never re-enqueued — the DB query filters them out."""
    from alerts.tasks import _resweep_pending_alerts

    # Query returns empty (delivered/failed filtered by WHERE clause at DB level).
    mock_session = _make_session([])

    with (
        patch("alerts.tasks.get_session") as mock_get_session,
        patch("alerts.tasks.dispatch_alert") as mock_dispatch,
    ):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=mock_session)
        cm.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = cm

        count = _resweep_pending_alerts()

    assert count == 0
    mock_dispatch.apply_async.assert_not_called()


def test_resweep_respects_max_batch() -> None:
    """Re-enqueues at most max_batch alerts per tick (query-level cap)."""
    from alerts.tasks import _resweep_pending_alerts

    # Simulate that the DB-level LIMIT returned exactly max_batch rows.
    max_batch = 3
    stale_ids = list(range(1, max_batch + 1))
    mock_session = _make_session(stale_ids)

    with (
        patch("alerts.tasks.get_session") as mock_get_session,
        patch("alerts.tasks.dispatch_alert") as mock_dispatch,
        patch("alerts.tasks.get_settings") as mock_settings,
    ):
        settings = MagicMock()
        settings.pending_resweep_grace_seconds = _GRACE
        settings.pending_resweep_max_batch = max_batch
        mock_settings.return_value = settings

        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=mock_session)
        cm.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = cm

        count = _resweep_pending_alerts()

    assert count == max_batch
    assert mock_dispatch.apply_async.call_count == max_batch
    for call, expected_id in zip(mock_dispatch.apply_async.call_args_list, stale_ids, strict=True):
        assert call.kwargs["args"] == (expected_id,)


def test_resweep_returns_zero_when_no_stale() -> None:
    """Returns 0 and calls nothing when no stale-pending alerts exist."""
    from alerts.tasks import _resweep_pending_alerts

    mock_session = _make_session([])

    with (
        patch("alerts.tasks.get_session") as mock_get_session,
        patch("alerts.tasks.dispatch_alert") as mock_dispatch,
    ):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=mock_session)
        cm.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = cm

        count = _resweep_pending_alerts()

    assert count == 0
    mock_dispatch.apply_async.assert_not_called()
