"""Offline OpenAPI schema dump — no server, no network (TASK-019 AC2).

Imports the FastAPI ``app`` object, calls ``app.openapi()`` (which builds the
schema synchronously from registered routes), and writes the result as
deterministic JSON (``sort_keys=True``) to the committed dump file used by the
frontend ``gen:api`` script.

Usage (from apps/trendPulse):
    JWT_SECRET=dump OAUTH_STATE_SECRET=dump \\
    GOOGLE_CLIENT_ID=dump GOOGLE_CLIENT_SECRET=dump \\
    uv run --directory backend python scripts/dump_openapi.py

The dummy auth-secret values satisfy the fail-fast ``Settings`` fields without
exposing real credentials.  ``SWAGGER_ENABLE`` is intentionally NOT required:
``app.openapi()`` constructs the schema from routes regardless of whether the
interactive docs endpoints are enabled (the two concerns are independent).
"""

import json
from pathlib import Path

# parents[0] = backend/scripts, parents[1] = backend, parents[2] = apps/trendPulse
_DUMP_PATH: Path = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "shared" / "api" / "openapi.json"
)


def main() -> None:
    """Dump the app OpenAPI schema to *_DUMP_PATH* and print the destination."""
    # Import here so the module-level side-effects (configure_logging, middleware
    # registration) run only when the script is actually executed.
    from api.main import app

    # Reset the cached schema so we always dump a fresh build from the current routes,
    # not a stale value that may have been cached by a previous import.
    app.openapi_schema = None
    schema = app.openapi()

    _DUMP_PATH.parent.mkdir(parents=True, exist_ok=True)
    _DUMP_PATH.write_text(
        json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(_DUMP_PATH)  # intentional stdout — make target feedback


if __name__ == "__main__":
    main()
