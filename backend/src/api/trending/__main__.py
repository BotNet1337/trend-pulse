"""CLI entrypoint for showcase-tenant bootstrap (TASK-039).

Run via:  uv run python -m api.trending.bootstrap  (inside the backend container)
Or via:   make showcase-init  (which calls this via docker compose exec)

Idempotent: safe to re-run. Commits on success, rolls back on error.
Prints the showcase user id to stdout (not the password — never printed).
"""

import logging
import sys

from storage.database import get_session

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    """Bootstrap the showcase tenant and exit with code 0 on success, 1 on error."""
    from api.trending.bootstrap import ensure_showcase_tenant

    try:
        with get_session() as session:
            user_id = ensure_showcase_tenant(session)
        logger.info("showcase-init: done, showcase user id=%s", user_id)
        sys.exit(0)
    except Exception:
        logger.exception("showcase-init: failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
