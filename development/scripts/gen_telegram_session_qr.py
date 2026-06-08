#!/usr/bin/env python
"""Generate a Telethon StringSession via QR login (no SMS/app code needed).

Use this when login codes don't arrive / are rate-limited (SendCodeUnavailable):
QR login uses auth.exportLoginToken, a different mechanism than code delivery.

You scan the QR with the Telegram app on the target technical account:
  Telegram → Settings → Devices → "Link Desktop Device" → scan the QR below.

Renders an auto-refreshing QR in the terminal (tokens expire ~30s, recreated
automatically). On success prints the StringSession; if 2FA is on, prompts for
the cloud password.

Run (from apps/trendPulse) — `qrcode` is pulled in just for this run via uv --with:
    TELEGRAM_API_ID=... TELEGRAM_API_HASH=... \
      ~/.local/bin/uv run --with qrcode --directory backend \
      python ../development/scripts/gen_telegram_session_qr.py

COMPLIANCE: dedicated technical accounts only; never a personal session. Treat
the printed StringSession like a password (-> sensitive.env, never git/logs).
"""

from __future__ import annotations

import asyncio
import os
import sys

import qrcode
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

_DEVICE = {"device_model": "Desktop", "system_version": "Windows 10", "app_version": "1.0"}
_QR_WAIT_SECONDS = 30  # token lifetime per QR; recreated on timeout


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"error: env var {name} is required (from my.telegram.org)")
    return value


def _print_qr(url: str) -> None:
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    print("\n" + "=" * 60)
    print("Scan with Telegram: Settings -> Devices -> Link Desktop Device")
    print("=" * 60)
    qr.print_ascii(invert=True)
    print("(QR auto-refreshes; keep this window open and scan)\n")


async def main() -> None:
    api_id = int(_require_env("TELEGRAM_API_ID"))
    api_hash = _require_env("TELEGRAM_API_HASH")

    client = TelegramClient(StringSession(), api_id, api_hash, **_DEVICE)
    await client.connect()
    try:
        if await client.is_user_authorized():
            print("already authorized")
        else:
            qr_login = await client.qr_login()
            while True:
                _print_qr(qr_login.url)
                try:
                    await qr_login.wait(_QR_WAIT_SECONDS)
                    break  # scanned + accepted
                except TimeoutError:
                    await qr_login.recreate()  # token expired -> new QR
                except SessionPasswordNeededError:
                    pw = input("Two-step (2FA) password: ")
                    await client.sign_in(password=pw)
                    break

        session_string = client.session.save()
        me = await client.get_me()
        handle = getattr(me, "username", None) or getattr(me, "phone", "?")
        print("\n=== logged in as:", handle, "===")
        print("\nStringSession (paste into TELEGRAM_POOL_SESSIONS, comma-separated):\n")
        print(session_string)
        print("\nKeep it SECRET. Done.")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
