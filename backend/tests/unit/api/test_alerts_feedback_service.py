"""Unit tests for the detail-only feedback fields of the alerts read service (TASK-064).

Covers (no live DB — exercises the pure helpers + a fake session):
- verdict smallint → string mapping ("up"/"down"); unknown verdict → None.
- _current_verdict returns None when no feedback row exists.
- _mint_feedback_tokens mints tokens that verify_feedback_token round-trips back
  to the correct alert_id + verdict.
- graceful degradation: empty jwt_secret → (None, None), no raise.
- AC4 invariant: list_alerts leaves the three feedback fields at None (no mint
  per-item) — the AlertRead default is None and the list builder never sets them.

Pure compute (no DB / no network) — runs under `make ci-fast`.
"""

from collections.abc import Sequence
from typing import Any

import pytest

from alerts.feedback_tokens import (
    VERDICT_DOWN,
    VERDICT_UP,
    verify_feedback_token,
)
from api.alerts import service
from api.alerts.schemas import AlertRead
from storage.models.alert_feedback import VERDICT_DOWN as VERDICT_DOWN_INT
from storage.models.alert_feedback import VERDICT_UP as VERDICT_UP_INT

_ALERT_ID = 4242


class _ScalarResult:
    """Minimal stand-in for the object returned by Session.execute()."""

    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _FakeSession:
    """Fake Session whose execute() returns a preset scalar (verdict lookup)."""

    def __init__(self, verdict_value: object) -> None:
        self._verdict_value = verdict_value
        self.executed: list[Any] = []

    def execute(self, stmt: object) -> _ScalarResult:
        self.executed.append(stmt)
        return _ScalarResult(self._verdict_value)


# ─── verdict int → str mapping ────────────────────────────────────────────────


def test_verdict_map_up() -> None:
    assert service._VERDICT_INT_TO_STR[VERDICT_UP_INT] == VERDICT_UP


def test_verdict_map_down() -> None:
    assert service._VERDICT_INT_TO_STR[VERDICT_DOWN_INT] == VERDICT_DOWN


def test_current_verdict_up() -> None:
    session = _FakeSession(VERDICT_UP_INT)
    assert service._current_verdict(session, _ALERT_ID) == VERDICT_UP  # type: ignore[arg-type]


def test_current_verdict_down() -> None:
    session = _FakeSession(VERDICT_DOWN_INT)
    assert service._current_verdict(session, _ALERT_ID) == VERDICT_DOWN  # type: ignore[arg-type]


def test_current_verdict_none_when_no_row() -> None:
    session = _FakeSession(None)
    assert service._current_verdict(session, _ALERT_ID) is None  # type: ignore[arg-type]


def test_current_verdict_unknown_int_maps_to_none() -> None:
    """An unexpected smallint (defence-in-depth) maps to None, never raises."""
    session = _FakeSession(99)
    assert service._current_verdict(session, _ALERT_ID) is None  # type: ignore[arg-type]


# ─── token minting (detail only) ──────────────────────────────────────────────


def test_mint_feedback_tokens_roundtrip() -> None:
    """Minted tokens verify back to the correct alert_id and verdict."""
    token_up, token_down = service._mint_feedback_tokens(_ALERT_ID)
    assert token_up is not None
    assert token_down is not None

    jwt_secret = service.get_settings().jwt_secret
    payload_up = verify_feedback_token(token_up, jwt_secret=jwt_secret)
    payload_down = verify_feedback_token(token_down, jwt_secret=jwt_secret)

    assert payload_up["alert_id"] == _ALERT_ID
    assert payload_up["verdict"] == VERDICT_UP
    assert payload_down["alert_id"] == _ALERT_ID
    assert payload_down["verdict"] == VERDICT_DOWN


def test_mint_feedback_tokens_empty_secret_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty jwt_secret → (None, None), no raise (graceful degradation)."""

    class _NoSecretSettings:
        jwt_secret = ""
        feedback_token_ttl_seconds = 604800

    monkeypatch.setattr(service, "get_settings", lambda: _NoSecretSettings())
    assert service._mint_feedback_tokens(_ALERT_ID) == (None, None)


def test_mint_feedback_tokens_mint_failure_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    """A minting failure is swallowed → (None, None), no raise."""

    def _boom(**_kwargs: object) -> str:
        raise RuntimeError("mint failed")

    monkeypatch.setattr(service, "sign_feedback_token", _boom)
    assert service._mint_feedback_tokens(_ALERT_ID) == (None, None)


# ─── AC4 — list does NOT mint tokens ──────────────────────────────────────────


def test_alert_read_defaults_are_none() -> None:
    """AlertRead built without feedback fields (list path) leaves them None."""
    from datetime import UTC, datetime

    item = AlertRead(
        id=1,
        score=80.0,
        topic="t",
        first_seen=datetime.now(UTC),
        channels_count=3,
        delivery_status="delivered",
    )
    assert item.feedback is None
    assert item.feedback_token_up is None
    assert item.feedback_token_down is None


def test_list_alerts_does_not_call_mint(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC4: list_alerts must never mint feedback tokens (no per-item HMAC)."""
    minted = False

    def _tracking_mint(_alert_id: int) -> tuple[str | None, str | None]:
        nonlocal minted
        minted = True
        return "x", "y"

    monkeypatch.setattr(service, "_mint_feedback_tokens", _tracking_mint)

    class _Result:
        def all(self) -> Sequence[object]:
            return []

    class _ListSession:
        def execute(self, _stmt: object) -> _Result:
            return _Result()

    class _ProUser:
        id = 1
        plan = "pro"

    resp = service.list_alerts(_ListSession(), user=_ProUser())  # type: ignore[arg-type]
    assert resp.items == []
    assert minted is False
