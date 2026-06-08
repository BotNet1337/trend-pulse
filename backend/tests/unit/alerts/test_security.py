"""AC7 — SSRF guard for user-supplied webhook URLs (`validate_webhook_url`).

DNS resolution is mocked (`socket.getaddrinfo`) so the allow/deny table is
deterministic and network-free under `make ci-fast`:

- scheme allow-list: only `https` (http/file/gopher/ftp rejected),
- host classification: loopback (127.0.0.1, ::1), link-local + metadata
  (169.254.x, 169.254.169.254), RFC1918 private ranges, 0.0.0.0 → rejected,
- a public https host resolving to a public IP → allowed,
- resolution failure → rejected (fail closed).
"""

import socket
from collections.abc import Callable

import pytest

from alerts.errors import WebhookValidationError
from alerts.security import validate_webhook_url


def _fake_getaddrinfo(ip: str) -> Callable[..., list[object]]:
    def _resolver(host: str, *args: object, **kwargs: object) -> list[object]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]

    return _resolver


def _patch_resolution(monkeypatch: pytest.MonkeyPatch, ip: str) -> None:
    monkeypatch.setattr("alerts.security.socket.getaddrinfo", _fake_getaddrinfo(ip))


def test_public_https_host_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_resolution(monkeypatch, "93.184.216.34")  # example.com (public)
    validate_webhook_url("https://hooks.example.com/alert")  # no raise


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.example.com/alert",  # plain http
        "file:///etc/passwd",  # file scheme
        "gopher://example.com",  # gopher scheme
        "ftp://example.com/x",  # ftp scheme
    ],
)
def test_non_https_scheme_rejected(url: str) -> None:
    with pytest.raises(WebhookValidationError):
        validate_webhook_url(url)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "169.254.169.254",  # cloud metadata
        "169.254.10.10",  # link-local
        "10.1.2.3",  # RFC1918 10/8
        "172.16.5.5",  # RFC1918 172.16/12
        "192.168.1.1",  # RFC1918 192.168/16
        "0.0.0.0",  # unspecified
    ],
)
def test_private_ipv4_rejected(monkeypatch: pytest.MonkeyPatch, ip: str) -> None:
    _patch_resolution(monkeypatch, ip)
    with pytest.raises(WebhookValidationError):
        validate_webhook_url("https://attacker.example.com/x")


@pytest.mark.parametrize("ip", ["::1", "fc00::1", "fe80::1"])
def test_private_ipv6_rejected(monkeypatch: pytest.MonkeyPatch, ip: str) -> None:
    _patch_resolution(monkeypatch, ip)
    with pytest.raises(WebhookValidationError):
        validate_webhook_url("https://attacker.example.com/x")


def test_resolution_failure_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(host: str, *args: object, **kwargs: object) -> list[object]:
        raise socket.gaierror("name resolution failed")

    monkeypatch.setattr("alerts.security.socket.getaddrinfo", _boom)
    with pytest.raises(WebhookValidationError):
        validate_webhook_url("https://does-not-resolve.example.com/x")


def test_missing_host_rejected() -> None:
    with pytest.raises(WebhookValidationError):
        validate_webhook_url("https:///no-host")
