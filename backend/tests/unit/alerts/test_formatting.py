"""AC1 (RED anchor) + AC3-shape — pure alert formatting / webhook payload.

AC1: `format_alert_message(view)` renders the overview §1 message format
(`🔥 Viral alert [crypto]`, the quoted title, `Score: 94`, `47 каналов`,
`first seen 14:02`) for a known alert view. Written FIRST; fails until
`alerts.formatting` exists (RED → GREEN).

AC3-shape: `build_webhook_payload(view)` produces EXACTLY the overview §4 JSON
keys (`event=viral_alert`, `topic`, `title`, `score`, `channels_count`,
`first_seen`, `velocity`).

Pure compute (no DB / no network) so the module runs under `make ci-fast`.
"""

from datetime import UTC, datetime

from alerts.formatting import AlertView, build_webhook_payload, format_alert_message

_VIEW = AlertView(
    topic="crypto",
    title="Bitcoin ETF approval",
    score=94.0,
    channels_count=47,
    first_seen=datetime(2025, 6, 8, 14, 2, 0, tzinfo=UTC),
    velocity=2.3,
)


def test_format_alert_message_contains_overview_fields() -> None:
    message = format_alert_message(_VIEW)
    assert "🔥 Viral alert [crypto]" in message
    assert '"Bitcoin ETF approval"' in message
    assert "Score: 94" in message
    assert "47 каналов" in message
    assert "first seen 14:02" in message


def test_format_alert_message_is_pure() -> None:
    before = _VIEW.score
    format_alert_message(_VIEW)
    assert _VIEW.score == before  # frozen view: no mutation


def test_build_webhook_payload_matches_overview_schema() -> None:
    payload = build_webhook_payload(_VIEW)
    assert payload == {
        "event": "viral_alert",
        "topic": "crypto",
        "title": "Bitcoin ETF approval",
        "score": 94,
        "channels_count": 47,
        "first_seen": "2025-06-08T14:02:00+00:00",
        "velocity": 2.3,
    }
