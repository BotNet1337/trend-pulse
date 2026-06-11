"""Generic email transport: render via templates service + send via SMTP.

Design invariants (TASK-025):
  - No vendor lock-in — SMTP parameters come entirely from `Settings`.
  - No hardcoded host/port/credentials anywhere; dev defaults → mailpit.
  - Rending HTML is the templates service's job; this module is a thin client.
  - Errors are always explicit: `EmailRenderError` / `EmailSendError`.
  - Uses stdlib `smtplib` (sync) — called from Celery worker tasks where sync
    context is natural (task-026/027 will call `send_templated_email` directly).
"""

import smtplib
from email.message import EmailMessage

import httpx

from config import Settings, get_settings


class EmailRenderError(RuntimeError):
    """Raised when the templates service returns a non-2xx status."""


class EmailSendError(RuntimeError):
    """Raised when the SMTP server rejects or fails the send."""


def render_email(
    template: str,
    props: dict[str, object],
    *,
    settings: Settings | None = None,
) -> str:
    """Render an email template via the templates service.

    Args:
        template:  Template path, e.g. ``"auth/verify-email"``.
        props:     Template props (validated by the node service via zod).
        settings:  Override for dependency injection / tests.

    Returns:
        Rendered HTML string.

    Raises:
        EmailRenderError: If the templates service returns a non-2xx response.
    """
    cfg = settings or get_settings()
    url = f"{cfg.templates_service_url}/render/{template}"

    # Transport-level failures (service down, DNS, timeout) must surface as the
    # module's explicit error too — not just non-2xx — so callers (task-026/027)
    # only ever catch EmailRenderError (symmetry with send_email's SMTP guard).
    try:
        with httpx.Client() as client:
            response = client.post(url, json=props, timeout=cfg.email_render_timeout_seconds)
    except httpx.HTTPError as exc:
        raise EmailRenderError(
            f"Templates service unreachable at {url!r} (template={template!r}): {exc}"
        ) from exc

    if response.status_code < 200 or response.status_code >= 300:
        raise EmailRenderError(
            f"Templates service returned {response.status_code} for "
            f"template={template!r}: {response.text[:256]}"
        )

    try:
        return str(response.json()["html"])
    except (ValueError, KeyError, TypeError) as exc:
        raise EmailRenderError(
            f"Templates service returned an unexpected body for template={template!r}: {exc}"
        ) from exc


def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    settings: Settings | None = None,
    headers: dict[str, str] | None = None,
) -> None:
    """Send an HTML email via generic SMTP.

    All connection parameters come from ``settings``:
      - ``smtp_host`` / ``smtp_port`` — server coordinates.
      - ``smtp_starttls`` — upgrade to TLS after connect (prod SMTP providers).
      - ``smtp_user`` / ``smtp_password`` — credentials; empty → no login
        (mailpit dev mode does not require authentication).
      - ``smtp_from`` — ``From`` header value.

    Args:
        to:       Recipient address.
        subject:  Email subject line.
        html:     Full HTML body.
        settings: Override for dependency injection / tests.
        headers:  Optional extra message headers (TASK-069: ``List-Unsubscribe``
                  on lifecycle emails). ``None`` → behaviour unchanged.

    Raises:
        EmailSendError: If the SMTP server rejects the send.
    """
    cfg = settings or get_settings()

    msg = EmailMessage()
    msg["From"] = cfg.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    for name, value in (headers or {}).items():
        msg[name] = value
    msg.set_content(html, subtype="html")

    try:
        # Bounded timeout so a hung SMTP server cannot block the Celery worker
        # indefinitely (smtplib defaults to a blocking socket with no timeout).
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=cfg.smtp_timeout_seconds) as server:
            if cfg.smtp_starttls:
                server.starttls()
            if cfg.smtp_user:
                server.login(cfg.smtp_user, cfg.smtp_password)
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        # OSError/socket.timeout covers connect failures + the bounded timeout
        # above; SMTPException covers protocol/auth/reject errors.
        raise EmailSendError(
            f"SMTP send failed to {to!r} via {cfg.smtp_host}:{cfg.smtp_port}: {exc}"
        ) from exc


def send_templated_email(
    *,
    to: str,
    template: str,
    props: dict[str, object],
    subject: str,
    settings: Settings | None = None,
    headers: dict[str, str] | None = None,
) -> None:
    """Render a template and send the resulting HTML via SMTP.

    Orchestrates :func:`render_email` → :func:`send_email`.  Either step
    may raise ``EmailRenderError`` or ``EmailSendError`` respectively.

    Args:
        to:       Recipient address.
        template: Template path, e.g. ``"auth/verify-email"``.
        props:    Props forwarded to the templates service.
        subject:  Email subject line (not taken from the render response, so
                  callers can override/localise it).
        settings: Override for dependency injection / tests.
        headers:  Optional extra message headers (TASK-069: ``List-Unsubscribe``
                  on lifecycle emails). ``None`` → behaviour unchanged.
    """
    cfg = settings or get_settings()
    html = render_email(template, props, settings=cfg)
    send_email(to=to, subject=subject, html=html, settings=cfg, headers=headers)
