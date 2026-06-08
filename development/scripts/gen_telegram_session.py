#!/usr/bin/env python
"""Generate a Telethon StringSession for ONE technical pool account (interactive).

Run it once per technical account. It logs in (phone -> code -> optional 2FA),
prints a StringSession line, then logs OUT of this temporary client so no live
session is left dangling. Paste the printed value into
`development/env/sensitive.env` (comma-separated in TELEGRAM_POOL_SESSIONS).

COMPLIANCE: use ONLY dedicated technical accounts (their own SIMs) — NEVER your
personal account's session. Public channels only. See overview §2/§7.

Usage (from apps/trendPulse, interactive):
    TELEGRAM_API_ID=12345 TELEGRAM_API_HASH=abc... \
      uv run --directory backend python ../development/scripts/gen_telegram_session.py

(api_id/api_hash come from https://my.telegram.org. Generate from the SAME
proxy/region you'll later operate the account on, for IP consistency.)
"""

from __future__ import annotations

import os
import sys

from telethon.sessions import StringSession
from telethon.sync import TelegramClient

# A stable, realistic device fingerprint — keep it CONSISTENT for this account
# across generation and operation (changing it between IPs looks like a takeover).
_DEVICE = {
    "device_model": "Desktop",
    "system_version": "Windows 10",
    "app_version": "1.0",
}


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"error: env var {name} is required (get it from my.telegram.org)")
    return value


def main() -> None:
    api_id = int(_require_env("TELEGRAM_API_ID"))
    api_hash = _require_env("TELEGRAM_API_HASH")

    # Empty StringSession() => a fresh login; .start() prompts phone + code (+2FA).
    with TelegramClient(StringSession(), api_id, api_hash, **_DEVICE) as client:
        session_string = client.session.save()
        me = client.get_me()
        handle = getattr(me, "username", None) or getattr(me, "phone", "?")
        print("\n=== logged in as:", handle, "===")
        print("\nStringSession (paste into TELEGRAM_POOL_SESSIONS, comma-separated):\n")
        print(session_string)
        print("\nKeep it SECRET (treat like a password). Done.")


if __name__ == "__main__":
    main()
