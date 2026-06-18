"""Unit tests for the public signals API + MCP server (T7).

Route + MCP tool return SignalPayload-shaped data via an INJECTED source — no DB.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import current_user
from api.signals.mcp import handle_request
from api.signals.router import get_signal_source, router
from api.signals.service import recent_signals, to_signal_out
from scorer.categorize import EventCategory
from scorer.noise_filter import SignalKind
from scorer.signal_payload import SignalPayload


def _payload(score: float = 42.0) -> SignalPayload:
    return SignalPayload(
        headline_score=score,
        signal_kind=SignalKind.ORGANIC,
        category=EventCategory.REGULATION,
        origin_channel=5,
        origin_at=1_700_000_000.0,
        total_channels=6,
        independent_channels=4.0,
        lead_time_to_confirmation_seconds=1800.0,
        narrative="SEC подала иск против биржи",
    )


class _FakeSource:
    def __init__(self, payloads: list[SignalPayload]) -> None:
        self._payloads = payloads

    def recent(self, limit: int) -> list[SignalPayload]:
        return self._payloads[:limit]


# ── service ──────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_to_signal_out_maps_fields() -> None:
    out = to_signal_out(_payload(50.0))
    assert out.headline_score == 50.0
    assert out.signal_kind is SignalKind.ORGANIC
    assert out.category is EventCategory.REGULATION
    assert out.independent_channels == 4.0


@pytest.mark.unit
def test_recent_signals_respects_limit() -> None:
    src = _FakeSource([_payload(), _payload(), _payload()])
    assert len(recent_signals(src, 2)) == 2


# ── REST route (injected source + auth bypass, no DB) ────────────────────────


def _client(source: _FakeSource) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_signal_source] = lambda: source
    app.dependency_overrides[current_user] = lambda: object()
    return TestClient(app)


@pytest.mark.unit
def test_get_signals_returns_payload_json() -> None:
    client = _client(_FakeSource([_payload(77.0)]))
    resp = client.get("/signals?limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["signals"]) == 1
    sig = body["signals"][0]
    assert sig["headline_score"] == 77.0
    assert sig["category"] == "regulation"
    assert sig["signal_kind"] == "organic"
    assert sig["independent_channels"] == 4.0


@pytest.mark.unit
def test_get_signals_limit_validation() -> None:
    client = _client(_FakeSource([]))
    assert client.get("/signals?limit=0").status_code == 422
    assert client.get("/signals?limit=1000").status_code == 422


# ── MCP server ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_mcp_tools_list() -> None:
    resp = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, _FakeSource([]))
    assert resp["result"]["tools"][0]["name"] == "list_signals"


@pytest.mark.unit
def test_mcp_tools_call_returns_signals() -> None:
    src = _FakeSource([_payload(88.0)])
    resp = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "list_signals", "arguments": {"limit": 5}},
        },
        src,
    )
    content = resp["result"]["content"]
    assert content[0]["headline_score"] == 88.0
    assert content[0]["category"] == "regulation"


@pytest.mark.unit
def test_mcp_unknown_method_errors() -> None:
    resp = handle_request({"jsonrpc": "2.0", "id": 3, "method": "nope"}, _FakeSource([]))
    assert resp["error"]["code"] == -32601
