"""Integration (G2) — alert delivery end-to-end (AC2/AC3/AC6).

Seeds a user (with Telegram + webhook config) + a cluster + a scored alert row in a
live Postgres, then runs `alerts.notifier.deliver` and asserts:

- AC3: the webhook receives a POST with the exact overview §4 JSON payload,
- AC2: the Telegram Bot API `sendMessage` is invoked (mocked — no real bot),
- AC6: the alert row is marked `delivered` with `delivered_at` set.

The webhook receiver is a tiny stdlib threaded HTTP server bound to loopback. The
SSRF guard would normally reject loopback, so it is patched OFF for this test only
(its deny behavior is covered exhaustively in the unit `test_security.py`). The
whole module is `integration`-marked and skipped without a DB.
"""

import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
from sqlalchemy.orm import Session

from alerts import backends, notifier
from storage.models import Alert, Cluster, Score, User
from storage.models.alerts import DELIVERY_STATUS_DELIVERED
from storage.models.users import PLAN_TEAM

pytestmark = pytest.mark.integration

_EMBEDDING_DIM = 384
_NOW = datetime(2025, 6, 8, 14, 2, 0, tzinfo=UTC)


class _CapturedRequest:
    body: dict[str, object] | None = None


def _make_handler(captured: _CapturedRequest) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            captured.body = json.loads(self.rfile.read(length).decode())
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_: object) -> None:
            return  # silence the test server

    return _Handler


@pytest.fixture
def webhook_server() -> Iterator[tuple[str, _CapturedRequest]]:
    captured = _CapturedRequest()
    server = HTTPServer(("127.0.0.1", 0), _make_handler(captured))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}/hook", captured
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _seed(session: Session) -> Alert:
    user = User(email="deliver@example.com", hashed_password="x" * 16)
    user.plan = PLAN_TEAM
    user.telegram_bot_token = "test-bot-token"
    user.telegram_chat_id = "555"
    session.add(user)
    session.flush()

    cluster = Cluster(
        user_id=user.id, topic="crypto", embedding=[0.1] + [0.0] * (_EMBEDDING_DIM - 1)
    )
    cluster.first_seen = _NOW
    session.add(cluster)
    session.flush()

    session.add(
        Score(
            user_id=user.id,
            cluster_id=cluster.id,
            velocity=2.3,
            engagement=1.0,
            cross_channel=0.5,
            viral_score=94.0,
        )
    )
    alert = Alert(
        user_id=user.id,
        cluster_id=cluster.id,
        score=94.0,
        channels_count=47,
        first_seen=_NOW,
    )
    session.add(alert)
    session.flush()
    return alert


def test_deliver_to_webhook_and_telegram(
    db_session: Session,
    webhook_server: tuple[str, _CapturedRequest],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook_url, captured = webhook_server
    alert = _seed(db_session)
    db_session.flush()
    # Point the Team user's webhook at the local fake receiver.
    user = db_session.get(User, alert.user_id)
    assert user is not None
    user.webhook_url = webhook_url
    db_session.flush()

    # The fake webhook is on loopback → the SSRF-safe client would (correctly) block
    # it, so swap in a plain client for THIS test only (deny behavior + DNS-rebinding
    # pinning are covered in unit test_security.py / test_backends.py).
    monkeypatch.setattr(
        backends,
        "build_ssrf_safe_client",
        lambda timeout_seconds: httpx.Client(timeout=timeout_seconds, follow_redirects=False),
    )

    # Mock the Telegram Bot API (no real bot): record the sendMessage call.
    telegram_calls: list[dict[str, object]] = []
    real_post = httpx.post

    def _fake_post(url: str, **kwargs: object) -> httpx.Response:
        if "api.telegram.org" in url:
            telegram_calls.append({"url": url, "json": kwargs.get("json")})
            return httpx.Response(200, request=httpx.Request("POST", url))
        return real_post(url, **kwargs)  # webhook → real local POST

    monkeypatch.setattr(backends.httpx, "post", _fake_post)

    status = notifier.deliver(db_session, alert)

    assert status == DELIVERY_STATUS_DELIVERED
    assert alert.delivery_status == DELIVERY_STATUS_DELIVERED
    assert alert.delivered_at is not None
    # AC3 — webhook received the overview §4 payload.
    assert captured.body == {
        "event": "viral_alert",
        "topic": "crypto",
        "title": "crypto",
        "score": 94,
        "channels_count": 47,
        "first_seen": "2025-06-08T14:02:00+00:00",
        "velocity": 2.3,
    }
    # AC2 — Telegram sendMessage invoked with chat_id + text.
    assert len(telegram_calls) == 1
    tg_json = telegram_calls[0]["json"]
    assert isinstance(tg_json, dict)
    assert tg_json["chat_id"] == "555"
    assert "🔥 Viral alert [crypto]" in str(tg_json["text"])
