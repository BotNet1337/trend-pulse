"""Google OAuth2 client (httpx-oauth) — configured from settings, not hardcoded.

The OAuth flow itself (state, code exchange, identity verification) lives inside
fastapi-users + httpx-oauth; we only supply the Google client id/secret from
`sensitive.env` (ADR-005). The router is wired in `api/main.py`.
"""

from httpx_oauth.clients.google import GoogleOAuth2

from config import get_settings


def build_google_oauth_client() -> GoogleOAuth2:
    """Instantiate the Google OAuth2 client from env-sourced credentials."""
    settings = get_settings()
    return GoogleOAuth2(settings.google_client_id, settings.google_client_secret)
