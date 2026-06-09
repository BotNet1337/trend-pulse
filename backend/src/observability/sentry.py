"""Sentry error-tracking initialisation (TASK-024).

Provides a single ``init_sentry(component)`` helper that is called once at
process startup (``api/main.py`` and ``celery_app.py``).  When ``SENTRY_DSN``
is empty the function returns immediately — Sentry is fully off and no network
calls are made (dev default, invariant).

Integrations:
- ``"api"``    → ``FastApiIntegration`` + ``StarletteIntegration``
- ``"worker"`` → ``CeleryIntegration``

Security (AC6): two layers keep secrets/PII out of Sentry:
1. ``include_local_variables=False`` — Sentry otherwise captures the repr() of
   every stacktrace frame's locals, which routinely hold secrets (Telegram
   StringSession/api_hash, passwords, the Settings object's credential fields).
   ``before_send`` cannot scrub frame vars reliably (they are repr strings), so
   the only robust fix is to not collect them at all.
2. The ``_scrub`` before_send hook removes/masks credentials, PII and raw post
   content from ``request``/``extra``/``contexts``/``breadcrumbs`` (recursing
   through nested dicts AND lists). Sensitive values become ``"[scrubbed]"`` or
   are dropped; a NEW event dict is returned (the original is never mutated).

Performance: ``_traces_sampler`` returns 0.0 for ``/health`` so the liveness
probe does not generate trace noise.
"""

from typing import Any, Literal, cast

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.types import Event, Hint

from config import get_settings

# Liveness probe path — excluded from trace sampling (named, not a magic literal).
_HEALTH_PATH = "/health"

# Header names (lower-cased) that carry credentials — must NEVER reach Sentry.
_SCRUB_HEADERS: frozenset[str] = frozenset({"authorization", "cookie"})

# Exact field names for PII / secret fields in event payloads (extra / request.data
# / contexts / breadcrumbs). Covers this project's concrete secrets (overview §7):
# Telegram session string + api_hash, NOWPayments key, email/password, Sentry/DB DSN.
_SCRUB_FIELD_EXACT: frozenset[str] = frozenset(
    {
        "password",
        "email",
        "telegram_bot_token",
        "api_hash",
        "api_key",
        "session",
        "dsn",
        "secret",
        "token",
    }
)

# Suffixes: any key whose lower-cased name ends with one of these is scrubbed.
# Targeted to this project's real secrets while avoiding benign false-positives:
# `_api_key`→nowpayments_api_key, `_api_hash`→telegram_api_hash, `_password`→
# postgres_password, `_session(s)`→telegram_pool_sessions, `_dsn`→sentry_dsn.
# (We deliberately do NOT use bare `_key`/`_hash` — they would scrub innocent
# fields like `sort_key`/`media_hash`.)
_SCRUB_FIELD_SUFFIXES: tuple[str, ...] = (
    "_token",
    "_secret",
    "_password",
    "_api_key",
    "_api_hash",
    "_session",
    "_sessions",
    "_dsn",
)

# Keys that may carry raw post content → dropped entirely, in EVERY scrubbed
# section (overview §7: raw content must never leave the process, not in logs nor
# in error telemetry).
_DROP_CONTENT_KEYS: frozenset[str] = frozenset({"text", "content", "body", "raw", "raw_text"})

# Bound recursion so a pathologically deep event cannot raise RecursionError inside
# before_send (which would silently drop the event).
_MAX_SCRUB_DEPTH = 12


def _should_scrub_field(key: str) -> bool:
    """True if a field name is a known PII / secret carrier."""
    lower = key.lower()
    if lower in _SCRUB_FIELD_EXACT:
        return True
    return any(lower.endswith(suffix) for suffix in _SCRUB_FIELD_SUFFIXES)


def _scrub_value(value: object, depth: int) -> object:
    """Recurse into dicts/lists; leave scalars untouched. Depth-bounded."""
    if depth >= _MAX_SCRUB_DEPTH:
        return "[scrubbed:too-deep]"
    if isinstance(value, dict):
        return _scrub_dict(cast(dict[str, Any], value), depth + 1)
    if isinstance(value, list):
        return [_scrub_value(item, depth + 1) for item in value]
    return value


def _scrub_dict(data: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    """Return a NEW dict: drop raw-content keys, mask secret/PII, recurse.

    Recurses into nested dicts AND lists (a list of dicts is a common shape for
    breadcrumbs/request bodies). Never mutates *data*.
    """
    result: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in _DROP_CONTENT_KEYS:
            continue  # raw content — drop entirely
        if _should_scrub_field(key):
            result[key] = "[scrubbed]"
        else:
            result[key] = _scrub_value(value, depth)
    return result


def _scrub_request(request_data: dict[str, Any]) -> dict[str, Any]:
    """Scrub the ``request`` section of a Sentry event.

    - ``headers``: remove ``authorization`` and ``cookie`` entries.
    - ``data``: dict → full scrub (drop content, mask secrets, recurse); non-dict
      (raw string / form list / unparsed body) → dropped wholesale (could be a raw
      body carrying credentials/content we cannot field-scrub).
    - Other keys (url/method/env): pass through (not sensitive).
    """
    result: dict[str, Any] = {}
    for key, value in request_data.items():
        if key == "headers" and isinstance(value, dict):
            result["headers"] = {
                k: v
                for k, v in cast(dict[str, Any], value).items()
                if k.lower() not in _SCRUB_HEADERS
            }
        elif key == "data":
            result["data"] = (
                _scrub_dict(cast(dict[str, Any], value))
                if isinstance(value, dict)
                else "[scrubbed]"
            )
        else:
            result[key] = value
    return result


def _scrub_breadcrumbs(breadcrumbs: dict[str, Any]) -> dict[str, Any]:
    """Scrub each breadcrumb's ``data`` (http/db crumbs can carry PII/secrets)."""
    values = breadcrumbs.get("values")
    if not isinstance(values, list):
        return breadcrumbs
    new_breadcrumbs: dict[str, Any] = dict(breadcrumbs)
    new_breadcrumbs["values"] = [
        _scrub_dict(cast(dict[str, Any], crumb)) if isinstance(crumb, dict) else crumb
        for crumb in values
    ]
    return new_breadcrumbs


def _scrub(event: Event, hint: Hint) -> Event | None:
    """Sentry ``before_send`` hook: scrub secrets/PII before the event is sent.

    Returns a NEW event dict (immutable pattern). Never mutates *event*. If any
    step is uncertain the field is dropped, not forwarded as-is.
    """
    # Event is a TypedDict under TYPE_CHECKING but opaque at runtime; cast to a
    # plain dict so we can rebuild the sensitive sections without mypy complaints.
    scrubbed: dict[str, Any] = cast(dict[str, Any], dict(event))

    request_raw = scrubbed.get("request")
    if isinstance(request_raw, dict):
        scrubbed["request"] = _scrub_request(cast(dict[str, Any], request_raw))

    extra_raw = scrubbed.get("extra")
    if isinstance(extra_raw, dict):
        scrubbed["extra"] = _scrub_dict(cast(dict[str, Any], extra_raw))

    contexts_raw = scrubbed.get("contexts")
    if isinstance(contexts_raw, dict):
        scrubbed["contexts"] = _scrub_dict(cast(dict[str, Any], contexts_raw))

    breadcrumbs_raw = scrubbed.get("breadcrumbs")
    if isinstance(breadcrumbs_raw, dict):
        scrubbed["breadcrumbs"] = _scrub_breadcrumbs(cast(dict[str, Any], breadcrumbs_raw))

    return cast("Event", scrubbed)


def _traces_sampler(sampling_context: dict[str, Any]) -> float:
    """Return 0.0 for /health (noise suppression), else the configured rate."""
    wsgi_env = sampling_context.get("wsgi_environ") or {}
    asgi_scope = sampling_context.get("asgi_scope") or {}
    path = wsgi_env.get("PATH_INFO", "") or asgi_scope.get("path", "")
    if path == _HEALTH_PATH:
        return 0.0
    return get_settings().sentry_traces_sample_rate


def init_sentry(component: Literal["api", "worker"]) -> None:
    """Initialise Sentry for the given process component (idempotent).

    A no-op when ``SENTRY_DSN`` is empty so dev environments never make Sentry
    network calls. Safe to call multiple times (Sentry's own ``init`` is
    idempotent within a process).
    """
    settings = get_settings()
    if not settings.sentry_dsn:
        # Explicit early return — Sentry stays fully uninitialised (invariant).
        return

    integrations: list[sentry_sdk.integrations.Integration]
    if component == "api":
        integrations = [FastApiIntegration(), StarletteIntegration()]
    else:
        integrations = [CeleryIntegration()]

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=settings.release,
        # `traces_sampler` fully governs trace sampling (it reads the configured
        # rate and zeroes /health); passing `traces_sample_rate` too would be a
        # dead, confusing duplicate since the sampler always wins.
        traces_sampler=_traces_sampler,
        send_default_pii=False,
        # SECURITY (AC6): do not capture stacktrace frame locals — they hold
        # secrets (Telegram session/api_hash, passwords, Settings creds) that
        # before_send cannot reliably scrub out of repr strings.
        include_local_variables=False,
        before_send=_scrub,
        integrations=integrations,
    )
