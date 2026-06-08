"""Watchlist CRUD API package (tenant-scoped; ADR-001/002).

Exports the FastAPI `router` for `api.main` to mount. One DB row = one watchlist
(single channel, numeric id) per the user decision documented in `schemas.py`.
"""

from api.watchlist.router import router

__all__ = ["router"]
