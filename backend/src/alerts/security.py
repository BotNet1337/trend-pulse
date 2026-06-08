"""SSRF guard for user-supplied webhook URLs (overview/security 5.5; AC7).

A webhook target is an arbitrary user-controlled URL the worker POSTs to — a
classic SSRF vector. The guard fails CLOSED:

1. scheme MUST be `https` (reject http/file/gopher/ftp/… — no plaintext, no
   non-HTTP schemes),
2. resolve EVERY address the host maps to and reject if ANY is private,
   loopback, link-local, multicast, reserved, or unspecified (RFC1918 10/8 ·
   172.16/12 · 192.168/16, 127.0.0.0/8, ::1, 169.254.0.0/16 incl. the
   169.254.169.254 metadata IP, 0.0.0.0, fc00::/7, …),
3. reject on resolution failure (a host we cannot classify is not trusted).

DNS-rebinding (TOCTOU) defence: validation and the actual connection MUST share
ONE resolution. A naive `validate_webhook_url(url)` followed by `httpx.post(url)`
re-resolves the host at connect time, so an attacker with a low-TTL record can
return a public IP during validation and a private/metadata IP at connect →
full SSRF bypass. We therefore resolve once, validate EVERY returned IP, and
pin the connection to a validated IP (`PinnedIPTransport`) while preserving the
original hostname for the `Host` header and TLS SNI / certificate verification.

A violation raises `WebhookValidationError` (a `PermanentDeliveryError`) so the
dispatcher never retries and never performs the POST. `ipaddress.is_global` is the
authoritative public/non-public classifier; we resolve via `socket.getaddrinfo`
(mockable in unit tests).
"""

import ipaddress
import socket
import ssl
from urllib.parse import urlparse

import httpx

from alerts.errors import WebhookValidationError

# Only TLS HTTP webhooks are accepted (no plaintext, no non-HTTP schemes).
_ALLOWED_SCHEME = "https"


def _classify_address(ip_text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Parse a resolved address; raise `WebhookValidationError` if non-global.

    `is_global` is False for private, loopback, link-local (incl. the
    169.254.169.254 metadata IP), multicast, reserved, and unspecified ranges,
    so a single check covers the whole deny-list for both IPv4 and IPv6.
    """
    address = ipaddress.ip_address(ip_text)
    if not address.is_global:
        raise WebhookValidationError("webhook host resolves to a non-public address")
    return address


def resolve_and_validate_host(host: str) -> str:
    """Resolve `host`, validate EVERY address, return one validated IP literal.

    The returned IP is the address a caller MUST connect to so that the validated
    resolution and the connection are the same (no re-resolution / DNS-rebinding
    window). Fails CLOSED: raises `WebhookValidationError` on resolution failure
    or if ANY resolved address is non-public.
    """
    try:
        resolved = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise WebhookValidationError("webhook host could not be resolved") from exc

    if not resolved:
        raise WebhookValidationError("webhook host resolved to no addresses")

    # Reject if ANY resolved address is non-public (a host with one public + one
    # private record could otherwise smuggle a request to an internal target).
    validated: list[str] = []
    for entry in resolved:
        sockaddr = entry[4]
        _classify_address(str(sockaddr[0]))
        validated.append(str(sockaddr[0]))
    return validated[0]


def validate_webhook_url(url: str) -> str:
    """Validate a webhook URL against SSRF; return one validated host IP literal.

    Raises `WebhookValidationError` if the URL is unsafe. The returned IP is the
    address a connection MUST be pinned to (see `PinnedIPTransport`) so the check
    and the connect share one DNS resolution.
    """
    parsed = urlparse(url)
    if parsed.scheme != _ALLOWED_SCHEME:
        raise WebhookValidationError(f"webhook scheme must be {_ALLOWED_SCHEME!r}")

    host = parsed.hostname
    if not host:
        raise WebhookValidationError("webhook URL has no host")

    return resolve_and_validate_host(host)


class PinnedIPTransport(httpx.HTTPTransport):
    """An `httpx` transport that re-resolves, re-validates, and pins to one IP.

    On EVERY request it resolves the URL host, validates every resolved address
    with the SSRF deny-list, then connects to a validated IP — making the SSRF
    check and the TCP connect share a SINGLE DNS resolution (closes the
    DNS-rebinding TOCTOU window). The original hostname is preserved for the
    `Host` header and for TLS SNI / certificate verification (`sni_hostname`
    extension), so HTTPS cert verification still validates against the real
    hostname and is never disabled.
    """

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if request.url.scheme != _ALLOWED_SCHEME:
            raise WebhookValidationError(f"webhook scheme must be {_ALLOWED_SCHEME!r}")
        if not host:
            raise WebhookValidationError("webhook URL has no host")

        # Resolve + validate, then pin to the validated IP. The connection goes to
        # THIS address — not a re-resolved one — so a rebind between check and
        # connect is impossible.
        validated_ip = resolve_and_validate_host(host)

        pinned_url = request.url.copy_with(host=validated_ip)
        # Preserve the original hostname for routing (Host) and TLS (SNI + cert).
        request.headers["Host"] = host
        request.extensions = {**request.extensions, "sni_hostname": host}
        request.url = pinned_url
        return super().handle_request(request)


def build_ssrf_safe_client(*, timeout_seconds: int) -> httpx.Client:
    """Build an `httpx.Client` whose connections are SSRF-validated + IP-pinned.

    TLS verification stays ON (default `ssl.create_default_context`); the cert is
    verified against the original hostname via the `sni_hostname` extension set by
    `PinnedIPTransport`. Redirects are NOT followed (a 3xx to an internal host must
    not bypass the guard).
    """
    ssl_context: ssl.SSLContext = ssl.create_default_context()
    transport = PinnedIPTransport(verify=ssl_context)
    return httpx.Client(
        transport=transport,
        timeout=timeout_seconds,
        follow_redirects=False,
    )
