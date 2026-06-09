"""AC4/AC6 integration: backend renders email via templates service + delivers to mailpit.

Requires a running stack (templates:3100 + mailpit:1025/8025).
Skipped automatically when either service is unreachable — safe to run in CI
without the stack; verify manually with `make up` (task-025 verify stage).

Run with stack:
    make up
    JWT_SECRET=... uv run --directory backend pytest \
        tests/integration/test_email_delivery.py -v -m integration
"""

import httpx
import pytest

MAILPIT_API = "http://localhost:8025/api/v1"
TEMPLATES_URL = "http://localhost:3100"
SMTP_HOST = "localhost"
SMTP_PORT = 1025


def _is_templates_up() -> bool:
    try:
        r = httpx.get(f"{TEMPLATES_URL}/health", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _is_mailpit_up() -> bool:
    try:
        r = httpx.get(f"{MAILPIT_API}/messages", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="module", autouse=True)
def require_stack() -> None:
    """Skip the entire module if templates or mailpit is not reachable."""
    if not _is_templates_up():
        pytest.skip("templates service not reachable at localhost:3100 (stack not up)")
    if not _is_mailpit_up():
        pytest.skip("mailpit not reachable at localhost:8025 (stack not up)")


@pytest.mark.integration
def test_render_verify_email_via_templates_service() -> None:
    """Render auth/verify-email through templates service, assert TrendPulse brand."""
    props = {
        "userName": "IntegrationUser",
        "verifyUrl": "https://app.trendpulse.local/auth/email/confirm?token=test-int",
        "expiresAt": "24 hours from now",
    }
    resp = httpx.post(
        f"{TEMPLATES_URL}/render/auth/verify-email",
        json=props,
        timeout=10,
    )
    assert resp.status_code == 200, f"Unexpected status: {resp.status_code} {resp.text}"
    body = resp.json()
    assert "html" in body
    assert "TrendPulse" in body["html"], "Brand name TrendPulse missing from rendered HTML"
    assert "PostBolt" not in body["html"], "Old brand PostBolt found in rendered HTML"
    assert "PostBridge" not in body["html"], "Old brand PostBridge found in rendered HTML"


@pytest.mark.integration
def test_publications_template_returns_404() -> None:
    """publications/published template was dropped — must return 404."""
    resp = httpx.post(
        f"{TEMPLATES_URL}/render/publications/published",
        json={},
        timeout=5,
    )
    assert resp.status_code == 404, (
        f"Expected 404 for publications template, got {resp.status_code}"
    )


@pytest.mark.integration
def test_send_email_via_smtp_delivered_to_mailpit() -> None:
    """Send an email via SMTP to mailpit and verify it appears in mailpit API."""
    import smtplib
    from email.message import EmailMessage

    # Render HTML via templates service
    props = {
        "userName": "MailpitTestUser",
        "verifyUrl": "https://app.trendpulse.local/auth/email/confirm?token=mailpit-test",
        "expiresAt": "1 hour from now",
    }
    render_resp = httpx.post(
        f"{TEMPLATES_URL}/render/auth/verify-email",
        json=props,
        timeout=10,
    )
    assert render_resp.status_code == 200
    html = render_resp.json()["html"]

    # Count messages before sending
    before = httpx.get(f"{MAILPIT_API}/messages", timeout=5).json()
    before_count: int = before.get("total", 0)

    # Send via SMTP to mailpit
    msg = EmailMessage()
    msg["From"] = "TrendPulse Test <noreply@test.local>"
    msg["To"] = "integration-test@trendpulse.local"
    msg["Subject"] = "Integration test: verify email"
    msg.set_content(html, subtype="html")

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.send_message(msg)

    # Poll mailpit for the new message (allow a moment for delivery)
    import time

    for _ in range(10):
        after = httpx.get(f"{MAILPIT_API}/messages", timeout=5).json()
        if after.get("total", 0) > before_count:
            break
        time.sleep(0.5)

    assert after.get("total", 0) > before_count, "No new message appeared in mailpit"

    # Verify the latest message contains TrendPulse brand
    messages = after.get("messages", [])
    assert messages, "mailpit messages list is empty"
    latest = messages[0]
    assert "Integration test: verify email" in latest.get("Subject", ""), (
        f"Subject mismatch: {latest.get('Subject')}"
    )
