"""Notifications package — email transport.

Only email-related functions are re-exported here; Celery task definitions
live in their own modules to avoid circular imports (celery_app → tasks →
notifications; if notifications imported celery_app it would cycle).
"""

from .email import (
    EmailRenderError,
    EmailSendError,
    render_email,
    send_email,
    send_templated_email,
)

__all__ = [
    "EmailRenderError",
    "EmailSendError",
    "render_email",
    "send_email",
    "send_templated_email",
]
