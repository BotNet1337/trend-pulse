# development/scripts

Operational helper scripts for the TrendPulse dev/ops environment.

| Script | Purpose |
|---|---|
| [`ansible-unpack.sh`](./ansible-unpack.sh) | Render `development/env/{deploy,sensitive}.env` from `ops/ansible/group_vars` (stub; real ansible-vault → task-012). Run via `make ansible-unpack`. |
| [`gen_telegram_session.py`](./gen_telegram_session.py) | Generate a Telethon `StringSession` for ONE technical pool account (interactive). See below. |

---

## `gen_telegram_session.py` — get Telegram pool session strings

Session strings are **generated**, not downloaded: you log into each **technical**
account once (phone → code → optional 2FA) and Telethon prints a `StringSession`
you paste into `sensitive.env`. Run it **once per account** (3–10 accounts).

### Prerequisites
1. `api_id` + `api_hash` from **https://my.telegram.org** → *API development tools*
   (one pair for the whole app; see the app-description guidance in the TASK-005
   thread / `docs/learnings.md`).
2. `uv` installed and `backend/` synced (`telethon` is a backend dependency):
   ```sh
   make ansible-unpack   # if you haven't materialized env yet (optional here)
   ```

### Run (interactive — needs phone + code input)
From `apps/trendPulse`:

```sh
TELEGRAM_API_ID=12345 TELEGRAM_API_HASH=your_api_hash \
  uv run --directory backend python ../development/scripts/gen_telegram_session.py
```

> Inside Claude Code, prefix with `!` so the interactive prompts work in-session:
> `! TELEGRAM_API_ID=12345 TELEGRAM_API_HASH=your_api_hash uv run --directory backend python ../development/scripts/gen_telegram_session.py`

It will prompt:
1. `Please enter your phone (or bot token):` → the technical account's number, e.g. `+1234567890`
2. `Please enter the code you received:` → the login code Telegram sends to that account
3. *(if 2FA is on)* `Please enter your password:` → the account's cloud password

Then it prints a long `StringSession` line (starts like `1ApWap...`). **That is the session string.**

### Where to put the output
Collect all accounts' strings, comma-separated, into **`development/env/sensitive.env`** (gitignored):

```dotenv
TELEGRAM_API_ID=12345
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_POOL_SESSIONS=1ApWap...acc1...,1BxYz...acc2...,1CqRs...acc3...
```

(The exact env keys are finalized in `config.py` during TASK-005. The real source
of truth for secrets is the Ansible vault — task-012; `sensitive.env` is the
locally-rendered copy and is `.gitignore`d.)

### Compliance & anti-ban (READ)
- Use **only dedicated technical accounts** (their own SIMs) — **never** your personal
  account's session. **Public channels only.** (overview §2/§7, CONVENTIONS.)
- Generate from the **same IP/proxy/region** you'll later operate the account on
  (IP consistency is the #1 anti-takeover/anti-ban signal).
- Keep the device fingerprint consistent (the script pins one).
- A session string is **as sensitive as a password** — only in `sensitive.env`,
  never in git or logs. Enable 2FA on each technical account.
- Full anti-ban operating guide: see the TASK-005 thread / `docs/learnings.md`.

### Troubleshooting
- `env var TELEGRAM_API_ID is required` → you didn't pass the env vars; prepend them as shown.
- `PhoneNumberBannedError` / `AuthKeyDuplicatedError` → that account/number is already
  banned or the session was used from another IP; use a different technical account.
- `FloodWaitError` during login → wait the indicated seconds and retry (don't hammer).
</content>
