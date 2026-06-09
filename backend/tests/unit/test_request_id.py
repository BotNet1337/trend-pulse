"""AC1 anchor: request_id in X-Request-ID header + in every log record.

RED phase: these tests MUST FAIL before observability/context.py and the
middleware/logging filter extensions exist.
"""

import logging
import logging.handlers
import uuid
from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def mini_app() -> FastAPI:
    """Minimal FastAPI app with log_requests middleware wired up."""
    from observability.logging import RequestIdFilter, configure_logging
    from observability.middleware import log_requests

    configure_logging()

    # Attach the RequestIdFilter to make request_id appear in all log records.
    root = logging.getLogger()
    for handler in root.handlers:
        # Avoid duplicate filters on repeated fixture calls.
        if not any(isinstance(f, RequestIdFilter) for f in handler.filters):
            handler.addFilter(RequestIdFilter())

    app = FastAPI()
    app.middleware("http")(log_requests)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "yes"}

    return app


@pytest.fixture
def client(mini_app: FastAPI) -> Generator[TestClient, None, None]:
    with TestClient(mini_app, raise_server_exceptions=True) as c:
        yield c


# ---------------------------------------------------------------------------
# Header tests
# ---------------------------------------------------------------------------


def test_response_has_request_id_header(client: TestClient) -> None:
    """Any request → response carries a valid uuid4 X-Request-ID header."""
    response = client.get("/ping")
    assert response.status_code == 200
    rid = response.headers.get("X-Request-ID")
    assert rid is not None, "X-Request-ID header must be present"
    # Must be a valid UUID.
    parsed = uuid.UUID(rid)
    assert str(parsed) == rid or parsed.hex == rid.replace("-", "")


def test_incoming_valid_request_id_propagated(client: TestClient) -> None:
    """A valid incoming X-Request-ID is echoed back unchanged."""
    incoming = str(uuid.uuid4())
    response = client.get("/ping", headers={"X-Request-ID": incoming})
    assert response.headers.get("X-Request-ID") == incoming


def test_incoming_invalid_request_id_ignored(client: TestClient) -> None:
    """An invalid/injected X-Request-ID is ignored — a fresh uuid is generated."""
    for bad in ["not-a-uuid", "../../etc/passwd", "' OR 1=1 --", ""]:
        response = client.get("/ping", headers={"X-Request-ID": bad})
        rid = response.headers.get("X-Request-ID")
        assert rid is not None
        assert rid != bad
        uuid.UUID(rid)  # must be a valid UUID


# ---------------------------------------------------------------------------
# Log-record filter test
# ---------------------------------------------------------------------------


def test_request_id_in_log_record() -> None:
    """With the RequestIdFilter on a handler, every log record carries request_id."""
    from observability.context import reset_request_id, set_request_id
    from observability.logging import RequestIdFilter

    expected_rid = str(uuid.uuid4())
    token = set_request_id(expected_rid)
    try:
        handler = logging.handlers.MemoryHandler(capacity=10)
        handler.addFilter(RequestIdFilter())
        logger = logging.getLogger("test.request_id_filter")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("test event")
        handler.flush()

        assert len(handler.buffer) >= 1
        record = handler.buffer[-1]
        assert hasattr(record, "request_id"), "record must have request_id attribute"
        assert record.request_id == expected_rid  # type: ignore[attr-defined]
    finally:
        reset_request_id(token)
        logger.removeHandler(handler)
