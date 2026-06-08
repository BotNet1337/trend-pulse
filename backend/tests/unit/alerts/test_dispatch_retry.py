"""AC5 — `dispatch_alert` retry policy (transient → retry → failed; permanent → failed).

The Celery task is exercised directly as a function with a fake `self` (bind=True)
and a patched `deliver` / `get_session`, so no broker or DB is needed. `self.retry`
raises a sentinel `_Retry` we assert on (mirrors Celery's `Retry` control flow).
"""

import pytest

from alerts import tasks
from alerts.errors import PermanentDeliveryError, TransientDeliveryError, WebhookValidationError
from storage.models.alerts import DELIVERY_STATUS_FAILED


class _Retry(Exception):
    """Stand-in for celery.exceptions.Retry raised by `self.retry`."""


class _FakeRequest:
    def __init__(self, retries: int) -> None:
        self.retries = retries


class _FakeTask:
    def __init__(self, retries: int) -> None:
        self.request = _FakeRequest(retries)
        self.retried_with: dict[str, object] | None = None

    def retry(self, **kwargs: object) -> _Retry:
        self.retried_with = kwargs
        return _Retry()


class _DummyAlert:
    id = 10


class _FakeSessionCtx:
    """Context manager yielding a session whose `get` returns a dummy alert."""

    def __enter__(self) -> "_FakeSessionCtx":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get(self, _model: object, _pk: int) -> _DummyAlert:
        return _DummyAlert()


def _patch_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "get_session", lambda: _FakeSessionCtx())


def test_transient_retries_when_attempts_remain(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_session(monkeypatch)

    def _boom(_session: object, _alert: object) -> str:
        raise TransientDeliveryError("network")

    monkeypatch.setattr(tasks, "deliver", _boom)
    task = _FakeTask(retries=0)

    with pytest.raises(_Retry):
        tasks._dispatch(task, 10)
    assert task.retried_with is not None
    assert "countdown" in task.retried_with


def test_transient_exhausted_marks_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_session(monkeypatch)
    marked: list[int] = []
    monkeypatch.setattr(tasks, "_mark_failed", lambda alert_id: marked.append(alert_id))

    def _boom(_session: object, _alert: object) -> str:
        raise TransientDeliveryError("network")

    monkeypatch.setattr(tasks, "deliver", _boom)
    # retries already at the max → no further retry, terminal failed (AC5).
    from config import get_settings

    task = _FakeTask(retries=get_settings().alert_max_retries)

    result = tasks._dispatch(task, 10)
    assert result == DELIVERY_STATUS_FAILED
    assert marked == [10]
    assert task.retried_with is None  # never retried


@pytest.mark.parametrize("error", [PermanentDeliveryError, WebhookValidationError])
def test_permanent_marks_failed_no_retry(
    monkeypatch: pytest.MonkeyPatch, error: type[Exception]
) -> None:
    _patch_session(monkeypatch)
    marked: list[int] = []
    monkeypatch.setattr(tasks, "_mark_failed", lambda alert_id: marked.append(alert_id))

    def _boom(_session: object, _alert: object) -> str:
        raise error("permanent")

    monkeypatch.setattr(tasks, "deliver", _boom)
    task = _FakeTask(retries=0)

    result = tasks._dispatch(task, 10)
    assert result == DELIVERY_STATUS_FAILED
    assert marked == [10]
    assert task.retried_with is None  # AC5 — permanent never retries
