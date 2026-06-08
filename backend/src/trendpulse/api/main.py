"""FastAPI application entrypoint.

The `/health` endpoint is intentionally pure (no DB/Redis call) so it answers
before infra/provisioning is ready and is safe for the nginx edge healthcheck.
"""

from typing import Literal, TypedDict

from fastapi import FastAPI

app = FastAPI(title="TrendPulse API")


class HealthResponse(TypedDict):
    """Liveness payload returned by `GET /health`."""

    status: Literal["ok"]


@app.get("/health")
def health() -> HealthResponse:
    """Liveness probe — returns 200 without touching any backing service."""
    return {"status": "ok"}
