---
id: TASK-103
title: TG pool >= 3 sessions — provisioning runbook (owner action)
status: owner-blocked
owner: infra
created: 2026-06-15
updated: 2026-06-15
tags: [reliability, collector, telegram, pool, runbook, owner-gated, SPOF]
---

# TASK-103 — TG pool >= 3 (provisioning runbook)

> Track A (reliability) #7 — the SINGLE biggest reliability SPOF (audit FM-1): prod runs
> `POOL_MIN_HEALTHY=1` with one technical Telegram session. If that one session dies
> (AuthKeyDuplicated/ban/revoke), ingest STOPS for every tenant until the owner re-mints it.
> The code already supports a 3–10 pool (`POOL_MAX=10`, `from_sessions` validates 1..10;
> rotation, FLOOD_WAIT cooldown, dead-session quarantine + now persistent quarantine TASK-102 all
> handle N>1). What's missing is purely OPERATIONAL: provision >= 3 real sessions. Owner has numbers.

## Why this is owner-gated (not a code PR)
1. Minting a Telethon `StringSession` is INTERACTIVE (phone number → SMS/Telegram code, or QR) —
   it cannot be done autonomously/headlessly by the loop.
2. Bumping `pool_min_healthy` to 3 BEFORE the sessions exist would make the pool report
   `degraded` (healthy 1 < target 3) and fire the `pool_below_target` ops alert continuously.
   So the config bump must land TOGETHER with the new sessions, not before.

## Runbook (owner)
1. **Mint >= 3 StringSessions** (one per phone number), e.g. a throwaway script:
   ```python
   from telethon.sync import TelegramClient
   from telethon.sessions import StringSession
   with TelegramClient(StringSession(), API_ID, API_HASH) as c:
       print(c.session.save())   # paste the printed string into the vault (step 2)
   ```
   Use the SAME `TELEGRAM_API_ID`/`TELEGRAM_API_HASH` as prod. Do this on a trusted machine;
   the printed string is a full-account credential — handle like a secret.
2. **Put them in the Ansible vault** as `vault_telegram_pool_sessions` — multiple sessions are
   newline/comma-separated per `telegram_pool_sessions(settings)` parsing
   (`ops/ansible/vault/sensitive.vault.yml`, edited with `ansible-vault edit`).
3. **Bump the target** to match: `ops/ansible/inventory/group_vars/prod.yml` → `pool_min_healthy: "3"`
   (currently "1"). Now the degraded-alert correctly fires only below 3 healthy.
4. **Deploy:** `make deploy` (rolling worker/beat update). The pool loads N sessions; `acquire()`
   rotates across them; one dead session no longer stops ingest (the others serve).
5. **Verify:** ops `pool_health` log shows `size>=3, healthy>=3, degraded=false`; kill/expire one
   session → ingest continues on the others, exactly one `auth_dead:{n}` alert, no `pool_exhausted`.

## Acceptance (when executed)
- [ ] >= 3 sessions in the vault; `pool_min_healthy=3` on prod.
- [ ] `pool_health`: size>=3, healthy>=3, degraded=false after deploy.
- [ ] One session death → ingest continues (no full stop), persistent quarantine (TASK-102) holds.

## Notes
- Hard rule (memory): NEVER reuse a pool session for backfill (AuthKeyDuplicated incident); the
  pool sessions are live-ingest only.
- Until done, the single-session SPOF is partially mitigated by: persistent quarantine (TASK-102),
  the repeating `pool_exhausted` + `ingest_stale` ops alerts (TASK-100/101), and external uptime
  (TASK-060, also owner-gated). Pool>=3 is the real fix.
- Tracked in MANUAL-TODO; status `owner-blocked` until sessions are provisioned.
