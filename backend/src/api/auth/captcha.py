"""Google reCAPTCHA v2 verification — sign-up bot protection.

Empty-secret = OFF: when ``settings.recaptcha_secret_key`` is unset (local dev,
or any host that hasn't provisioned the secret) verification is a no-op that
always passes, so the sign-up flow is never challenged locally. In production
the secret is provisioned via sensitive.env and a missing/invalid client token
fails the sign-up with HTTP 400.

Security invariants:
  - The secret is sent only to Google's siteverify endpoint, never logged.
  - Network/timeout/parse errors fail CLOSED (treated as a failed challenge)
    when reCAPTCHA is enabled — a bot must not slip through on infra hiccups.
"""

import logging

import httpx

from config import get_settings

logger = logging.getLogger(__name__)

# Google's server-side verification endpoint (reCAPTCHA v2/v3 share it).
_SITEVERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"

# Tight timeout — this sits on the sign-up critical path.
_VERIFY_TIMEOUT_SECONDS = 5.0


def recaptcha_enabled() -> bool:
    """True when a reCAPTCHA secret is configured (prod); False in local dev."""
    return bool(get_settings().recaptcha_secret_key)


async def verify_recaptcha(token: str | None) -> bool:
    """Return True when the client reCAPTCHA token is valid (or CAPTCHA is OFF).

    When disabled (no secret) → always True (local dev never challenges).
    When enabled → False if the token is missing/empty or Google rejects it, and
    False (fail-closed) on any network/parse error.
    """
    secret = get_settings().recaptcha_secret_key
    if not secret:
        # CAPTCHA disabled — no challenge in local/dev. Never blocks sign-up.
        return True

    if not token:
        return False

    try:
        async with httpx.AsyncClient(timeout=_VERIFY_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _SITEVERIFY_URL,
                data={"secret": secret, "response": token},
            )
            response.raise_for_status()
            payload = response.json()
    except Exception:
        # Fail closed when enabled — never log the secret or the token.
        logger.warning("recaptcha verification failed (network/parse error)")
        return False

    return bool(payload.get("success", False))
