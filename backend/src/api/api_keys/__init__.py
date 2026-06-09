"""api_keys package — lightweight re-export of the router (no Celery/heavy imports).

Importing `api.api_keys` in api/main.py only pulls in the router; service,
schemas and constants are imported transitively but do not trigger side effects.
"""

from api.api_keys.router import router

__all__ = ["router"]
