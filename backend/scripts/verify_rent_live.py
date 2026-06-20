"""Live SMSPVA RENTAL gap test: rent a real-SIM number (service opt29) -> register a Telegram
account (no proxy by default) -> report HONESTLY whether Telegram accepted. The hypothesis:
real-SIM RENTAL numbers pass where cheap Activation numbers gave PhoneNumberInvalid.

OWNER-APPROVED spend. Rental is NOT free (min 7 days, ~price_day x 7). Run `--price` FIRST
(0 spend) to see the per-day price + stock for opt29 before committing.

Run:
  cd backend && uv run python scripts/verify_rent_live.py --price --countries DE,PL,RO,KZ,UA
  cd backend && uv run python scripts/verify_rent_live.py --countries DE,PL,RO [--proxy socks5://..]

On success the rented number is KEPT (finish=no-op) so the account survives probation.
On any failure the rental is released (delete). Secrets (apikey, session, proxy) never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path

import httpx

_ENV_FILES = (
    Path(__file__).resolve().parents[2] / "development" / "env" / "deploy.env",
    Path(__file__).resolve().parents[2] / "development" / "env" / "sensitive.env",
)


def _load_env() -> None:
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
from factory.constants import (  # noqa: E402
    RENT_BASE_PATH,
    RENT_SVC_TELEGRAM,
    SMSPVA_BASE_URL,
)
from factory.errors import SmsNumberUnavailableError  # noqa: E402
from factory.providers.smspva_rent import build_smspva_rent_provider  # noqa: E402
from factory.registrar.telethon import TelethonRegistrar  # noqa: E402

_CODE_POLL_TIMEOUT_SECONDS = 300


async def _price_probe(api_key: str, countries: list[str]) -> None:
    """Read-only opt29 per-day price + stock per country (no spend)."""
    url = f"{SMSPVA_BASE_URL}{RENT_BASE_PATH}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        for c in countries:
            params = {
                "method": "getdataWithProviders",
                "apikey": api_key,
                "country": c,
                "dtype": "week",
                "dcount": "1",
            }
            try:
                r = await client.get(url, params=params)
                body = r.json()
            except (httpx.HTTPError, ValueError):
                print(f"  {c}: probe failed (transport/parse)")
                continue
            services = (
                (body.get("data") or {}).get("services")
                if isinstance(body.get("data"), dict)
                else None
            )
            row = None
            if isinstance(services, list):
                row = next(
                    (s for s in services if str(s.get("service")) == RENT_SVC_TELEGRAM), None
                )
            if row is None:
                print(f"  {c}: no opt29 (Telegram) rental offered")
                continue
            price_day = row.get("price_day")
            stock = row.get("totalCount")
            week = Decimal(str(price_day)) * 7 if price_day is not None else None
            print(f"  {c}: opt29 price_day={price_day}  ~week(7d)={week}  stock={stock}")


async def _amain(countries: list[str], proxy: str | None, *, price_only: bool) -> int:
    s = get_settings()
    if not s.smspva_api_key:
        print("ERROR: SMSPVA_API_KEY not set.", file=sys.stderr)
        return 2
    if s.telegram_api_id is None or s.telegram_api_hash is None:
        print(
            "ERROR: TELEGRAM_API_ID/HASH not set — cannot run the real registrar.", file=sys.stderr
        )
        return 2

    if price_only:
        print("[price] opt29 (Telegram rental) per-day price + stock (0 spend):")
        await _price_probe(s.smspva_api_key, countries)
        print("[price] done. Re-run without --price to rent + register.")
        return 0

    provider = build_smspva_rent_provider(
        api_key=s.smspva_api_key,
        dtype=s.account_factory_rent_dtype,
        dcount=s.account_factory_rent_dcount,
    )
    registrar = TelethonRegistrar(api_id=s.telegram_api_id, api_hash=s.telegram_api_hash)
    try:
        bal = await provider.balance()
        via = f"socks5://***@{proxy.split('@')[-1]}" if proxy else "NO proxy (direct)"
        print(f"[setup] SMSPVA balance ${bal}; renting opt29 real-SIM; register via {via}")

        purchased = None
        used = None
        for c in countries:
            try:
                print(f"[rent] create+activate in {c} ({s.account_factory_rent_dtype})…")
                purchased = await provider.buy_number(country=c, service=RENT_SVC_TELEGRAM)
                used = c
                break
            except SmsNumberUnavailableError:
                print(f"[rent] {c}: no stock — next.")
        if purchased is None:
            print(f"[rent] FAIL: no opt29 stock in {countries}. 0 spend.")
            return 1
        masked = "+" + "*" * max(len(purchased.phone) - 4, 0) + purchased.phone[-4:]
        print(
            f"[rent] OK: rented {masked} in {used} (rent_id={purchased.order_id}) — number is LIVE."
        )

        async def code_cb() -> str:
            print("[code] waiting for Telegram SMS on the rented number…")
            return await provider.poll_code(
                purchased.order_id, timeout_seconds=_CODE_POLL_TIMEOUT_SECONDS
            )

        try:
            print("[register] send_code + sign_in/sign_up…")
            registered = await registrar.register(
                phone=purchased.phone, code_cb=code_cb, proxy=proxy
            )
        except Exception as exc:
            print(f"[register] ❌ TELEGRAM REJECTED: {type(exc).__name__}: {exc}")
            print("[release] deleting the rental…")
            await provider.cancel(purchased.order_id)
            print(f"[result] GAP NOT closed ({used}, rental) — Telegram rejected. Rental released.")
            return 1

        # success — KEEP the rental (finish is a no-op; the real-SIM stays for probation re-login)
        await provider.finish(purchased.order_id)
        print(
            f"[register] ✅ TELEGRAM ACCEPTED — account created, tg_user_id={registered.tg_user_id}"
        )
        print("[result] GAP CLOSED: a real-SIM RENTAL number registered a fresh Telegram account.")
        print("[note] rental KEPT alive (re-login window). Session withheld (secret).")
        return 0
    finally:
        await provider.aclose()


def main() -> int:
    p = argparse.ArgumentParser(
        description="Live SMSPVA rental registration gap test (owner-approved spend)."
    )
    p.add_argument(
        "--countries", default="DE,PL,RO,KZ,UA,NO", help="Comma ISO list, tried in order."
    )
    p.add_argument(
        "--proxy", default=None, help="Optional SOCKS5 URI to register through (default: no proxy)."
    )
    p.add_argument(
        "--price", action="store_true", help="Only probe opt29 price+stock — NO rent, NO spend."
    )
    a = p.parse_args()
    countries = [c.strip().upper() for c in a.countries.split(",") if c.strip()]
    try:
        return asyncio.run(_amain(countries, a.proxy, price_only=a.price))
    except Exception as exc:
        print(f"ERROR: rental test failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
