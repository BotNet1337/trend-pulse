"""AC4/AC6 + plan gating — notifier orchestration (DB-free via fakes).

The notifier reads the alert/user/cluster/score through the SQLAlchemy `Session`
API (`session.get`, `session.scalar`); a tiny fake session returns seeded objects
so the unit tests need no DB. Backends are mocked at the `alerts.notifier` level.

- AC4: an already-`delivered` alert → strict no-op (no backend send).
- AC6: a successful Telegram send → `delivered` + `delivered_at` set.
- Plan gating: a free-plan user with a webhook URL → webhook channel is skipped.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from alerts import notifier
from alerts.backends import DeliveryResult, TelegramTarget, WebhookTarget
from storage.models.alerts import (
    DELIVERY_STATUS_DELIVERED,
    DELIVERY_STATUS_PENDING,
    Alert,
)
from storage.models.clusters import Cluster
from storage.models.users import PLAN_FREE, PLAN_PRO, User

_NOW = datetime(2025, 6, 8, 14, 2, 0, tzinfo=UTC)


class _FakeSession:
    """Minimal stand-in for a SQLAlchemy Session used by the notifier."""

    def __init__(self, *, user: User, cluster: Cluster, velocity: float | None) -> None:
        self._user = user
        self._cluster = cluster
        self._velocity = velocity

    def get(self, model: type[Any], pk: int) -> Any:
        if model is User:
            return self._user
        if model is Cluster:
            return self._cluster
        return None

    def scalar(self, _stmt: object) -> float | None:
        return self._velocity


def _alert(status: str = DELIVERY_STATUS_PENDING) -> Alert:
    alert = Alert(
        user_id=1,
        cluster_id=2,
        score=94.0,
        channels_count=47,
        first_seen=_NOW,
    )
    alert.id = 10
    alert.delivery_status = status
    alert.delivery_attempts = 0
    return alert


def _user(*, plan: str, telegram: bool, webhook: bool) -> User:
    user = User(email="u@example.com", hashed_password="x")
    user.id = 1
    user.plan = plan
    user.telegram_bot_token = "tok" if telegram else None
    user.telegram_chat_id = "chat" if telegram else None
    user.webhook_url = "https://hooks.example.com/x" if webhook else None
    return user


def _cluster() -> Cluster:
    cluster = Cluster(user_id=1, topic="crypto", embedding=[0.0] * 384)
    cluster.id = 2
    return cluster


class _RecordingBackend:
    name = "rec"

    def __init__(self) -> None:
        self.sent: list[object] = []

    def send(self, view: object, target: object) -> DeliveryResult:
        self.sent.append(target)
        return DeliveryResult(ok=True, backend=self.name, detail="sent")


def test_already_delivered_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _RecordingBackend()
    monkeypatch.setattr(notifier, "TelegramBotBackend", lambda **_: backend)
    monkeypatch.setattr(notifier, "WebhookBackend", lambda **_: backend)
    session = _FakeSession(
        user=_user(plan=PLAN_PRO, telegram=True, webhook=True), cluster=_cluster(), velocity=2.3
    )
    alert = _alert(status=DELIVERY_STATUS_DELIVERED)

    status = notifier.deliver(session, alert)  # type: ignore[arg-type]

    assert status == DELIVERY_STATUS_DELIVERED
    assert backend.sent == []  # AC4 — no send at all


def test_success_marks_delivered(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _RecordingBackend()
    monkeypatch.setattr(notifier, "TelegramBotBackend", lambda **_: backend)
    session = _FakeSession(
        user=_user(plan=PLAN_FREE, telegram=True, webhook=False), cluster=_cluster(), velocity=2.3
    )
    alert = _alert()

    status = notifier.deliver(session, alert)  # type: ignore[arg-type]

    assert status == DELIVERY_STATUS_DELIVERED  # AC6
    assert alert.delivery_status == DELIVERY_STATUS_DELIVERED
    assert alert.delivered_at is not None
    assert len(backend.sent) == 1
    assert isinstance(backend.sent[0], TelegramTarget)


def test_free_plan_skips_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    tg = _RecordingBackend()
    wh = _RecordingBackend()
    monkeypatch.setattr(notifier, "TelegramBotBackend", lambda **_: tg)
    monkeypatch.setattr(notifier, "WebhookBackend", lambda **_: wh)
    # Free plan WITH a webhook URL set → webhook must be gated out.
    session = _FakeSession(
        user=_user(plan=PLAN_FREE, telegram=True, webhook=True), cluster=_cluster(), velocity=2.3
    )
    alert = _alert()

    notifier.deliver(session, alert)  # type: ignore[arg-type]

    assert len(tg.sent) == 1
    assert all(not isinstance(t, WebhookTarget) for t in tg.sent)
    assert wh.sent == []  # webhook backend never invoked


def test_pro_plan_uses_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    tg = _RecordingBackend()
    wh = _RecordingBackend()
    monkeypatch.setattr(notifier, "TelegramBotBackend", lambda **_: tg)
    monkeypatch.setattr(notifier, "WebhookBackend", lambda **_: wh)
    session = _FakeSession(
        user=_user(plan=PLAN_PRO, telegram=False, webhook=True), cluster=_cluster(), velocity=2.3
    )
    alert = _alert()

    status = notifier.deliver(session, alert)  # type: ignore[arg-type]

    assert status == DELIVERY_STATUS_DELIVERED
    assert len(wh.sent) == 1
    assert isinstance(wh.sent[0], WebhookTarget)


def test_no_channel_raises_and_marks_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession(
        user=_user(plan=PLAN_FREE, telegram=False, webhook=False), cluster=_cluster(), velocity=2.3
    )
    alert = _alert()
    with pytest.raises(notifier.NoChannelConfiguredError):
        notifier.deliver(session, alert)  # type: ignore[arg-type]
