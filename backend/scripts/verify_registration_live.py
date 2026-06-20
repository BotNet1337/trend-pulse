"""Live END-TO-END gap test: buy SMSPVA number -> register a Telegram account THROUGH a
SOCKS5 proxy -> report HONESTLY whether Telegram accepted (vs the prior bare-number
`PhoneNumberInvalidError`). Refunds the number on any failure. OWNER-APPROVED spend.

This answers the epic's headline question empirically: does routing registration through a
mobile/residential proxy make Telegram accept an SMS-service number?

It uses the REAL `SmsPvaProvider` + `TelethonRegistrar` (same components the factory wires),
so the result reflects production behavior. It loads the rendered env files itself (docker
env_file format) so it needs no bash sourcing. Secrets (session, proxy uri) are never printed.

Run:  cd backend && uv run python scripts/verify_registration_live.py \
          --proxy 'socks5://user:pass@host:port' [--countries MD,RU,KE] [--dry]
  --dry  = balance + telegram-creds check only, NO buy, NO spend.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# --- load rendered env files into os.environ BEFORE importing config ---
_ENV_FILES = (
    Path(__file__).resolve().parents[2] / "development" / "env" / "deploy.env",
    Path(__file__).resolve().parents[2] / "development" / "env" / "sensitive.env",
)


def _load_env() -> None:
    """Minimal docker-env_file loader (KEY=VALUE, ignore comments/blanks). Tolerant of
    values bash `source` can't parse; never overrides an already-set var."""
    for path in _ENV_FILES:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip()


_load_env()

from config import get_settings  # noqa: E402
from factory.constants import SMSPVA_DEFAULT_SERVICE  # noqa: E402
from factory.errors import SmsNumberUnavailableError  # noqa: E402
from factory.providers.smspva import build_smspva_provider  # noqa: E402
from factory.registrar.telethon import TelethonRegistrar  # noqa: E402

_CODE_POLL_TIMEOUT_SECONDS = 180


async def _amain(proxy: str, countries: list[str], *, dry: bool) -> int:
    s = get_settings()
    if not s.smspva_api_key:
        print("ERROR: SMSPVA_API_KEY not set in env.", file=sys.stderr)
        return 2
    if s.telegram_api_id is None or s.telegram_api_hash is None:
        print(
            "ERROR: TELEGRAM_API_ID/HASH not set — cannot run the REAL registrar.", file=sys.stderr
        )
        return 2

    provider = build_smspva_provider(api_key=s.smspva_api_key)
    registrar = TelethonRegistrar(api_id=s.telegram_api_id, api_hash=s.telegram_api_hash)
    try:
        bal = await provider.balance()
        print(f"[setup] SMSPVA ${bal}; tg creds present; service={SMSPVA_DEFAULT_SERVICE}")
        print(f"[setup] registering THROUGH proxy (masked): socks5://***@{proxy.split('@')[-1]}")
        if dry:
            print("[dry] balance + creds OK. No buy, no spend. Re-run without --dry to register.")
            return 0

        # buy the first country that has Telegram stock (no-stock raises before any charge)
        purchased = None
        used_country = None
        for c in countries:
            try:
                print(f"[buy] trying {c}…")
                purchased = await provider.buy_number(country=c, service=SMSPVA_DEFAULT_SERVICE)
                used_country = c
                break
            except SmsNumberUnavailableError:
                print(f"[buy] {c}: no stock — next.")
        if purchased is None:
            print(f"[buy] FAIL: no Telegram stock in {countries}. 0 spend.")
            return 1
        masked = "+" + "*" * max(len(purchased.phone) - 4, 0) + purchased.phone[-4:]
        print(f"[buy] OK: number {masked} in {used_country} (order={purchased.order_id}).")

        async def code_cb() -> str:
            print("[code] waiting for SMS code via SMSPVA…")
            return await provider.poll_code(
                purchased.order_id, timeout_seconds=_CODE_POLL_TIMEOUT_SECONDS
            )

        # the moment of truth — register THROUGH the proxy
        try:
            print("[register] send_code + sign_in/sign_up THROUGH the proxy…")
            registered = await registrar.register(
                phone=purchased.phone, code_cb=code_cb, proxy=proxy
            )
        except Exception as exc:
            # honest: report the EXACT failure class (bare numbers gave PhoneNumberInvalid)
            print(f"[register] ❌ TELEGRAM REJECTED: {type(exc).__name__}: {exc}")
            print("[refund] releasing the number (cancel)…")
            await provider.cancel(purchased.order_id)
            print(f"[result] GAP NOT closed ({used_country}+proxy) — Telegram rejected. Refunded.")
            return 1

        # success
        await provider.finish(purchased.order_id)
        print(
            f"[register] ✅ TELEGRAM ACCEPTED — account created, tg_user_id={registered.tg_user_id}"
        )
        print("[result] GAP CLOSED (this attempt): account registered THROUGH the proxy.")
        print("[note] session withheld (secret). Account live; factory would hold it on probation.")
        return 0
    finally:
        await provider.aclose()


def main() -> int:
    p = argparse.ArgumentParser(
        description="Live registration-through-proxy gap test (owner-approved spend)."
    )
    p.add_argument("--proxy", required=True, help="SOCKS5 URI to register through (secret).")
    p.add_argument(
        "--countries",
        default="MD,RU,KE,ID,VN",
        help="Comma ISO list, tried in order (match the proxy country first).",
    )
    p.add_argument(
        "--dry", action="store_true", help="Balance + creds check only — no buy, no spend."
    )
    a = p.parse_args()
    countries = [c.strip().upper() for c in a.countries.split(",") if c.strip()]
    try:
        return asyncio.run(_amain(a.proxy, countries, dry=a.dry))
    except Exception as exc:
        print(f"ERROR: live registration test failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
