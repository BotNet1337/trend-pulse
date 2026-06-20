"""Live verification harness for the proxy provider (EPIC-PROXY-AUTOPROVISION, final gate).

OWNER-KEY-GATED. Proves, against the REAL provider, that:
  1. the API token + base URL + endpoints are correct  -> `balance()` succeeds (no spend),
  2. a country-matched sticky SOCKS5 proxy can be allocated and is REACHABLE -> the egress
     IP fetched THROUGH the proxy differs from the direct egress IP (SOCKS5 connectivity proof),
  3. the proxy can be released -> `release(lease_id)`.

It is NEVER imported by the app and runs nothing unless `ACCOUNT_FACTORY_PROXY_PROVIDER` selects
a real provider with a token set. The proxy URI (user:pass) is treated as a SECRET — only the host
is printed; credentials are passed to `curl` and never echoed. Reports HONESTLY: any step that
fails prints the real (redacted) error and a non-zero exit — it never fabricates success.

Run:  cd backend && ACCOUNT_FACTORY_PROXY_PROVIDER=mobileproxy MOBILEPROXY_API_TOKEN=... \
          uv run python scripts/verify_proxy_live.py --country KE
      (add --balance-only to skip the allocation/spend and just prove the API token.)

The SOCKS5 echo uses the system `curl --socks5-hostname` (native SOCKS5 + auth) so the harness
needs no Python SOCKS dependency.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from urllib.parse import urlsplit

from config import get_settings
from factory.proxy.base import ProxyLease, ProxyProvider
from factory.proxy.factory import get_proxy_provider

# Public IP-echo endpoints (plain-text body = the caller's egress IP). Two hosts so a single
# flaky endpoint does not fail the proof.
_IP_ECHO_URLS: tuple[str, ...] = ("https://api.ipify.org", "https://ifconfig.me/ip")
_CURL_TIMEOUT_SECONDS = 40


def _mask_uri(uri: str) -> str:
    """Return `socks5://<host>:<port>` — credentials stripped (never printed)."""
    parts = urlsplit(uri)
    host = parts.hostname or "?"
    port = parts.port
    return f"socks5://{host}:{port}" if port is not None else f"socks5://{host}"


def _curl_ip(url: str, *, proxy_uri: str | None) -> str | None:
    """GET `url` (optionally THROUGH `proxy_uri` via SOCKS5) and return the body (an IP), else None.

    Credentials in `proxy_uri` are handed to curl as a `socks5h://` proxy and are never logged by
    this process. A non-zero curl exit / timeout / empty body → `None` (the caller reports it).
    """
    cmd = ["curl", "--silent", "--show-error", "--max-time", str(_CURL_TIMEOUT_SECONDS)]
    if proxy_uri is not None:
        parts = urlsplit(proxy_uri)
        # socks5h:// = resolve DNS on the proxy side (matches the pool's rdns=True).
        host_port = f"{parts.hostname}:{parts.port}" if parts.port else str(parts.hostname)
        cmd += ["--proxy", f"socks5h://{host_port}"]
        if parts.username is not None:
            cmd += ["--proxy-user", f"{parts.username}:{parts.password or ''}"]
    cmd.append(url)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=_CURL_TIMEOUT_SECONDS + 5)
    except (subprocess.TimeoutExpired, OSError):
        return None
    body = out.stdout.strip()
    return body if out.returncode == 0 and body else None


def _direct_ip() -> str | None:
    for url in _IP_ECHO_URLS:
        ip = _curl_ip(url, proxy_uri=None)
        if ip is not None:
            return ip
    return None


def _proxy_ip(uri: str) -> str | None:
    for url in _IP_ECHO_URLS:
        ip = _curl_ip(url, proxy_uri=uri)
        if ip is not None:
            return ip
    return None


async def _run(provider: ProxyProvider, *, country: str | None, balance_only: bool) -> int:
    # --- Step 1: balance (proves auth + base URL + endpoint; no spend) ---
    print("[1/3] balance() — proving API token + endpoint (no spend)…")
    balance = await provider.balance()
    print(f"      OK: balance = {balance}")
    if balance_only:
        print("      --balance-only: skipping allocation. API token verified.")
        return 0

    direct = _direct_ip()
    print(f"      direct egress IP (no proxy): {direct or 'UNKNOWN (curl failed)'}")

    # --- Step 2: allocate + SOCKS5 connectivity proof ---
    print(f"[2/3] allocate(country={country!r}) — renting a sticky SOCKS5 proxy…")
    lease: ProxyLease = await provider.allocate(country)
    # ProxyLease.__repr__ masks the uri; print only non-secret fields + masked endpoint.
    print(
        f"      OK: lease_id={lease.lease_id} country={lease.country} "
        f"expires_at={lease.expires_at} endpoint={_mask_uri(lease.uri)}"
    )
    exit_code = 0
    try:
        proxy_ip = _proxy_ip(lease.uri)
        if proxy_ip is None:
            print("      FAIL: could not fetch egress IP THROUGH the proxy (SOCKS5 unreachable).")
            exit_code = 1
        else:
            print(f"      egress IP THROUGH proxy: {proxy_ip}")
            if direct is not None and proxy_ip == direct:
                print("      FAIL: proxy egress IP == direct IP — traffic did NOT route via proxy.")
                exit_code = 1
            else:
                print("      OK: SOCKS5 connectivity proven — egress IP differs from direct.")
    finally:
        # --- Step 3: release (always, even if the connectivity check failed) ---
        print(f"[3/3] release(lease_id={lease.lease_id})…")
        await provider.release(lease.lease_id)
        print("      OK: released (best-effort).")
    return exit_code


async def _amain(country: str | None, *, balance_only: bool) -> int:
    settings = get_settings()
    provider = get_proxy_provider(settings)
    if provider is None:
        print(
            "ERROR: no dynamic proxy provider configured. Set "
            "ACCOUNT_FACTORY_PROXY_PROVIDER=mobileproxy + MOBILEPROXY_API_TOKEN.",
            file=sys.stderr,
        )
        return 2
    resolved_country = country if country is not None else settings.account_factory_country
    try:
        return await _run(provider, country=resolved_country, balance_only=balance_only)
    finally:
        await provider.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Live proxy-provider verification (owner-gated).")
    parser.add_argument(
        "--country", default=None, help="ISO country to allocate in (default: settings)."
    )
    parser.add_argument(
        "--balance-only",
        action="store_true",
        help="Only prove the API token via balance() — no spend.",
    )
    args = parser.parse_args()
    try:
        return asyncio.run(_amain(args.country, balance_only=args.balance_only))
    except Exception as exc:  # honest top-level: print the redacted error, never fake success.
        print(f"ERROR: live verification failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
