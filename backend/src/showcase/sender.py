"""Showcase TG sender — best-effort httpx sendMessage wrapper (TASK-044).

`send_showcase_post(token, chat_id, text, *, base_url, timeout)` POSTs a
plain-text message to the Telegram Bot API. Designed after the ops-bot pattern
in `observability/pool_health.py::notify_ops`:

- Empty token OR chat_id → silent no-op + WARNING (once per process start
  is acceptable; callers check before calling but defensive guard is here too).
- HTTP non-2xx → WARNING + return False (next beat tick retries).
- Network exception → WARNING with exc_type only (NOT the token, NOT the URL
  which embeds the token) + return False.
- Unexpected exception → WARNING + return False; NEVER raises.
- Returns True on confirmed success (status 2xx), False otherwise.

Security:
- Token NEVER appears in log messages, URLs logged, or repr output.
- Only exc_type (not exc) is logged on failure — no leakage via exception
  chain that could contain the URL with the embedded token.

Import note: does NOT import celery_app or ORM models — safe in any context.
"""

from __future__ import annotations

import logging

import httpx

from observability.logging import log_event

logger = logging.getLogger(__name__)

# HTTP status threshold — any code >= this is an error response.
_HTTP_ERROR_FLOOR: int = 400

# Warn-once flag: logged when creds are missing to avoid log flooding on every
# beat tick. Stored as a module-level set (reason → bool) so each distinct
# missing-credential reason is logged at most once per process lifetime.
_WARNED_MISSING: set[str] = set()


def send_showcase_post(
    token: str,
    chat_id: str,
    text: str,
    *,
    base_url: str,
    timeout: int,
) -> bool:
    """Send a post to the showcase TG channel via sendMessage.

    Args:
        token:    Showcase bot token (secret — NEVER logged).
        chat_id:  Target channel chat id.
        text:     Pre-built post text (sanitized aggregate — no raw content).
        base_url: Telegram API base URL (from settings.telegram_api_base_url).
        timeout:  HTTP timeout in seconds.

    Returns:
        True on success (2xx), False on any failure (caller retries next tick).
    """
    # Guard: empty token or chat_id → no-op + warn-once.
    if not token or not chat_id:
        reason = "showcase_missing_token" if not token else "showcase_missing_chat_id"
        if reason not in _WARNED_MISSING:
            _WARNED_MISSING.add(reason)
            logger.warning(
                "showcase_autopost disabled — missing credentials",
                extra={"reason": reason},
            )
        return False

    url = f"{base_url.rstrip('/')}/bot{token}/sendMessage"
    body = {"chat_id": chat_id, "text": text}

    try:
        response = httpx.post(url, json=body, timeout=timeout)
        if response.status_code >= _HTTP_ERROR_FLOOR:
            # Log status code (not the URL — it embeds the token).
            logger.warning(
                "showcase_autopost HTTP error",
                extra={"status_code": response.status_code},
            )
            log_event("showcase_send_failed", reason="http_error", status_code=response.status_code)
            return False

        # Fix #7: do NOT log chat_id — it is a static per-deployment value;
        # logging it on every success adds noise without value.
        log_event("showcase_post_sent")
        return True

    except httpx.HTTPError as exc:
        # exc_type only — exception message or repr may contain the URL with the token.
        logger.warning(
            "showcase_autopost delivery failed",
            extra={"exc_type": type(exc).__name__},
        )
        log_event("showcase_send_failed", reason="http_exception", exc_type=type(exc).__name__)
        return False

    except Exception as exc:
        # Broad safety net: sender must NEVER raise (beat must not crash).
        # Log only exc_type — never exc or url (token safety).
        logger.warning(
            "showcase_autopost unexpected error — suppressed",
            extra={"exc_type": type(exc).__name__},
        )
        return False
