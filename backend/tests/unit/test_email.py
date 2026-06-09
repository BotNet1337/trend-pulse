"""AC3/AC5 RED→GREEN anchor: backend email module — render_email + send_email.

Tests:
  - render_email makes correct HTTP POST to templates service (mocked httpx)
  - render_email propagates HTTP errors as EmailRenderError
  - send_email builds MIME and sends via SMTP (mocked smtplib)
  - send_email handles SMTP failures as EmailSendError
  - send_templated_email orchestrates render→send
  - All config sourced from settings — no hardcoded values
"""

from email.message import EmailMessage
from unittest.mock import MagicMock, patch

import httpx
import pytest

from config import Settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides: object) -> Settings:
    """Build a Settings instance with test-safe values."""
    defaults: dict[str, object] = dict(
        jwt_secret="test-secret",
        oauth_state_secret="test-oauth-secret",
        google_client_id="test-gci",
        google_client_secret="test-gcs",
        templates_service_url="http://templates-test:3100",
        smtp_host="mailpit-test",
        smtp_port=1025,
        smtp_from="TrendPulse Test <noreply@test.local>",
        smtp_starttls=False,
        smtp_user="",
        smtp_password="",
        email_render_timeout_seconds=5,
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# render_email tests
# ---------------------------------------------------------------------------


class TestRenderEmail:
    def test_makes_post_to_correct_url(self) -> None:
        """render_email calls POST {templates_service_url}/render/{template}."""
        from notifications.email import render_email

        settings = _make_settings()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "html": "<html>Hello TrendPulse</html>",
            "subject": "Verify your email",
        }

        with patch("notifications.email.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client
            mock_client.post.return_value = mock_response

            result = render_email(
                "auth/verify-email",
                {"userName": "Alice", "verifyUrl": "http://x", "expiresAt": "now"},
                settings=settings,
            )

        mock_client.post.assert_called_once_with(
            "http://templates-test:3100/render/auth/verify-email",
            json={"userName": "Alice", "verifyUrl": "http://x", "expiresAt": "now"},
            timeout=5,
        )
        assert result == "<html>Hello TrendPulse</html>"

    def test_raises_on_4xx(self) -> None:
        """render_email raises EmailRenderError on 4xx."""
        from notifications.email import EmailRenderError, render_email

        settings = _make_settings()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 404
        mock_response.text = "Template not found"

        with patch("notifications.email.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client
            mock_client.post.return_value = mock_response

            with pytest.raises(EmailRenderError, match="404"):
                render_email("auth/nonexistent", {}, settings=settings)

    def test_raises_on_5xx(self) -> None:
        """render_email raises EmailRenderError on 5xx."""
        from notifications.email import EmailRenderError, render_email

        settings = _make_settings()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        mock_response.text = "Internal error"

        with patch("notifications.email.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client
            mock_client.post.return_value = mock_response

            with pytest.raises(EmailRenderError, match="500"):
                render_email("auth/verify-email", {}, settings=settings)

    def test_raises_on_transport_error(self) -> None:
        """render_email wraps httpx transport errors (service down) in EmailRenderError."""
        from notifications.email import EmailRenderError, render_email

        settings = _make_settings()
        with patch("notifications.email.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client
            mock_client.post.side_effect = httpx.ConnectError("connection refused")

            with pytest.raises(EmailRenderError, match="unreachable"):
                render_email("auth/verify-email", {}, settings=settings)

    def test_raises_on_unexpected_body(self) -> None:
        """render_email wraps a 200 with a missing/invalid `html` field."""
        from notifications.email import EmailRenderError, render_email

        settings = _make_settings()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"subject": "S"}  # no "html"

        with patch("notifications.email.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client
            mock_client.post.return_value = mock_response

            with pytest.raises(EmailRenderError, match="unexpected body"):
                render_email("auth/verify-email", {}, settings=settings)

    def test_uses_settings_url_not_hardcoded(self) -> None:
        """render_email URL comes from settings, not a magic literal."""
        from notifications.email import render_email

        custom_url = "http://custom-templates:9999"
        settings = _make_settings(templates_service_url=custom_url)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"html": "<p>OK</p>", "subject": "S"}

        with patch("notifications.email.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client
            mock_client.post.return_value = mock_response

            render_email("auth/verify-email", {}, settings=settings)

        call_url = mock_client.post.call_args[0][0]
        assert call_url.startswith(custom_url)


# ---------------------------------------------------------------------------
# send_email tests
# ---------------------------------------------------------------------------


class TestSendEmail:
    def test_connects_to_settings_host_port(self) -> None:
        """send_email connects to smtp_host:smtp_port from settings."""
        from notifications.email import send_email

        settings = _make_settings(smtp_host="mysmtp.test", smtp_port=2525)

        with patch("notifications.email.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp.__exit__ = MagicMock(return_value=False)
            mock_smtp_cls.return_value = mock_smtp

            send_email(
                to="user@example.com",
                subject="Test subject",
                html="<p>Hello</p>",
                settings=settings,
            )

        mock_smtp_cls.assert_called_once_with(
            "mysmtp.test", 2525, timeout=settings.smtp_timeout_seconds
        )

    def test_sends_message_with_correct_fields(self) -> None:
        """send_email builds EmailMessage with From/To/Subject/html."""
        from notifications.email import send_email

        settings = _make_settings(
            smtp_from="TrendPulse <noreply@test.local>",
        )
        sent_messages: list[EmailMessage] = []

        with patch("notifications.email.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp.__exit__ = MagicMock(return_value=False)
            mock_smtp_cls.return_value = mock_smtp
            mock_smtp.send_message.side_effect = lambda msg: sent_messages.append(msg)

            send_email(
                to="recipient@example.com",
                subject="Hello world",
                html="<p>Content</p>",
                settings=settings,
            )

        assert len(sent_messages) == 1
        msg = sent_messages[0]
        assert msg["From"] == "TrendPulse <noreply@test.local>"
        assert msg["To"] == "recipient@example.com"
        assert msg["Subject"] == "Hello world"

    def test_starttls_called_when_enabled(self) -> None:
        """send_email calls starttls() when smtp_starttls=True."""
        from notifications.email import send_email

        settings = _make_settings(smtp_starttls=True)

        with patch("notifications.email.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp.__exit__ = MagicMock(return_value=False)
            mock_smtp_cls.return_value = mock_smtp

            send_email(
                to="u@example.com",
                subject="S",
                html="<p>H</p>",
                settings=settings,
            )

        mock_smtp.starttls.assert_called_once()

    def test_starttls_not_called_when_disabled(self) -> None:
        """send_email does NOT call starttls() when smtp_starttls=False."""
        from notifications.email import send_email

        settings = _make_settings(smtp_starttls=False)

        with patch("notifications.email.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp.__exit__ = MagicMock(return_value=False)
            mock_smtp_cls.return_value = mock_smtp

            send_email(
                to="u@example.com",
                subject="S",
                html="<p>H</p>",
                settings=settings,
            )

        mock_smtp.starttls.assert_not_called()

    def test_login_called_when_user_set(self) -> None:
        """send_email calls login() when smtp_user is non-empty."""
        from notifications.email import send_email

        settings = _make_settings(smtp_user="myuser", smtp_password="secret")

        with patch("notifications.email.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp.__exit__ = MagicMock(return_value=False)
            mock_smtp_cls.return_value = mock_smtp

            send_email(
                to="u@example.com",
                subject="S",
                html="<p>H</p>",
                settings=settings,
            )

        mock_smtp.login.assert_called_once_with("myuser", "secret")

    def test_login_not_called_when_user_empty(self) -> None:
        """send_email does NOT call login() when smtp_user is empty (mailpit dev mode)."""
        from notifications.email import send_email

        settings = _make_settings(smtp_user="", smtp_password="")

        with patch("notifications.email.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp.__exit__ = MagicMock(return_value=False)
            mock_smtp_cls.return_value = mock_smtp

            send_email(
                to="u@example.com",
                subject="S",
                html="<p>H</p>",
                settings=settings,
            )

        mock_smtp.login.assert_not_called()

    def test_raises_email_send_error_on_smtp_failure(self) -> None:
        """send_email raises EmailSendError when SMTP raises."""
        import smtplib

        from notifications.email import EmailSendError, send_email

        settings = _make_settings()

        with patch("notifications.email.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp.__exit__ = MagicMock(return_value=False)
            mock_smtp_cls.return_value = mock_smtp
            mock_smtp.send_message.side_effect = smtplib.SMTPException("connection refused")

            with pytest.raises(EmailSendError, match="connection refused"):
                send_email(
                    to="u@example.com",
                    subject="S",
                    html="<p>H</p>",
                    settings=settings,
                )


# ---------------------------------------------------------------------------
# send_templated_email orchestration
# ---------------------------------------------------------------------------


class TestSendTemplatedEmail:
    def test_orchestrates_render_then_send(self) -> None:
        """send_templated_email calls render_email then send_email."""
        from notifications import email as email_module

        settings = _make_settings()

        with (
            patch.object(email_module, "render_email", return_value="<p>HTML</p>") as mock_render,
            patch.object(email_module, "send_email") as mock_send,
        ):
            email_module.send_templated_email(
                to="user@example.com",
                template="auth/verify-email",
                props={"userName": "Bob", "verifyUrl": "http://x", "expiresAt": "1h"},
                subject="Verify",
                settings=settings,
            )

        mock_render.assert_called_once_with(
            "auth/verify-email",
            {"userName": "Bob", "verifyUrl": "http://x", "expiresAt": "1h"},
            settings=settings,
        )
        mock_send.assert_called_once_with(
            to="user@example.com",
            subject="Verify",
            html="<p>HTML</p>",
            settings=settings,
        )
