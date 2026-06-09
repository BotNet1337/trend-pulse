"""Alerts read API package (tenant-scoped, read-only; TASK-016 C4).

Exports the FastAPI `router` for `api.main` to mount.
GET /alerts  — paginated list of the caller's alerts (with history window by plan).
GET /alerts/{id} — detail for one alert (404 on foreign or missing).
"""

from api.alerts.router import router

__all__ = ["router"]
