---
id: TASK-129
title: Proxy-per-session — encrypted proxy column + SOCKS5 passthrough to Telethon
status: review
owner: backend
created: 2026-06-19
updated: 2026-06-19
baseline_commit: acb9d1ead373ebd99f5dd570dcc75ff0c1625546
branch: ""
tags: [telegram, pool, proxy, reliability, layer-a]
---

# TASK-129 — Proxy-per-session (Layer A1)

> One SOCKS5 proxy per pool session so accounts don't all egress from the single VPS IP
> (IP-correlation → mass ban under load). Fail-open: no proxy configured → today's behaviour.

## Context
Telethon clients are built in `backend/src/collector/telegram/client.py:50-66`
(`build_telethon_client(*, api_id, api_hash)` → `_factory(session)` →
`TelegramClient(StringSession(session), api_id, api_hash)`) — **no proxy passed today**. Sessions
live in `pool_sessions` (`storage/models/pool_sessions.py`, encrypted via `EncryptedString`,
ADR-008). The factory is consumed by `AccountPool.from_sessions()` (`collector/telegram/account_pool.py`)
and by `qr_login.py`. Pool loader: `collector/registry.py::_build_telegram_collector`.
Supersedes the TASK-059 "no per-account proxy" deferral (owner reversed; see epic).

## Goal
A nullable, **encrypted** `proxy` column on `pool_sessions` holding a SOCKS5 URI
(`socks5://user:pass@host:port`). When present for a session, its Telethon client connects through
that proxy; when absent, behaviour is byte-identical to today. Proxy string treated as a secret.

## Discussion
- Q: Proxy scope — per-session or global? → A: per-session → Decision: column on `pool_sessions`,
  threaded per client; matches "1 proxy per account" anti-ban guidance.
- Q: Encrypt the proxy? → A: yes → Decision: it carries `user:pass` credentials → `EncryptedString`
  like `session_string`; never logged.
- Q: Proxy format/parse? → A: SOCKS5 URI → Decision: parse to Telethon's `(socks.SOCKS5, host, port,
  True, user, pass)` tuple in a pure helper `parse_socks5_proxy()` with a named-constant default port;
  invalid string → domain error, fail-closed for that one session only (logged, slot skipped), not a crash.

## Scope
- Touch ONLY: `backend/migrations/versions/0026_pool_sessions_proxy.py` (new, down_revision `0025`);
  `storage/models/pool_sessions.py` (+`proxy` col); `storage/pool_session_store.py`
  (`StoredSession`/`upsert_revive_or_add` carry optional `proxy`); `collector/telegram/client.py`
  (factory accepts proxy + `parse_socks5_proxy` helper); `collector/telegram/account_pool.py`
  (pass per-session proxy to factory in `from_sessions`/`revive_slot`); `collector/registry.py`
  (load proxy from store rows); `collector/constants.py` (proxy default port + col width const).
- Do NOT touch: rotation/quarantine logic, pool-health, API, frontend, sharding (TASK-131).
- Blast radius: `pool_sessions` schema (additive nullable), Telethon factory signature (internal).

## Acceptance Criteria
- [ ] Given a `pool_sessions` row with a valid `proxy`, When the pool builds its client, Then the
      Telethon client is constructed with that SOCKS5 proxy tuple (asserted via fake factory capturing kwargs).
- [ ] Given a row with NULL proxy, When the pool builds, Then no proxy is passed (today's path).
- [ ] Given an invalid proxy string, When building that slot, Then a domain error is raised/logged and
      only that slot is skipped — other slots build normally.
- [ ] Migration `0026` applies and rolls back; proxy stored as Fernet ciphertext (raw-SQL assert).

## Plan
1. `migrations/versions/0026_pool_sessions_proxy.py` — `add_column pool_sessions.proxy` (encrypted String, nullable).
2. `storage/models/pool_sessions.py` — `proxy: Mapped[str | None]` via `EncryptedString`.
3. `collector/constants.py` — `SOCKS5_DEFAULT_PORT`, `POOL_SESSION_PROXY_MAX`.
4. `collector/telegram/client.py` — `parse_socks5_proxy(uri)` pure fn; `build_telethon_client` factory
   signature `_factory(session, proxy=None)`; pass `proxy=` to `TelegramClient`.
5. `collector/telegram/account_pool.py` — thread per-session proxy into factory calls.
6. `storage/pool_session_store.py` + `collector/registry.py` — carry/load `proxy`.

## Invariants
- No proxy configured anywhere → behaviour byte-identical to today (regression-guarded by test).
- Proxy string never logged / never in Redis / never in API response.
- One bad proxy degrades exactly one slot, never the whole pool.

## Edge cases
- Malformed proxy URI → `InvalidProxyError`, slot skipped. → Missing port → `SOCKS5_DEFAULT_PORT`.
- Proxy without auth (`socks5://host:port`) → user/pass None.

## Test plan
- unit: `parse_socks5_proxy` valid/invalid/no-auth; factory passes proxy tuple (extend `conftest.py` FakeClient to capture); one-bad-slot isolation.
- integration: `0026` round-trip + ciphertext assert (mirror `test_pool_session_store.py`).

## Checkpoints
current_step: 6
baseline_commit: acb9d1ead373ebd99f5dd570dcc75ff0c1625546
branch: "gsd/phase-129-proxy-per-session"
lock: "executor-task129"
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: failing test → minimal code)
- [x] 4 verify (G2 — tests + migration round-trip + factory-proxy behavioural assert)
- [x] 5 review (auto, adversarial — 2 HIGH + 2 LOW fixed in debug run 1, re-verified green)
- [x] 5.5 security (touches secrets — proxy creds + session — PASS, 5/5 invariants hold)
- [ ] 6 ship (PR)
- [ ] 7 learnings (auto)
debug_runs:
  - run: 1
    trigger: review HIGH x2
    findings: "(1) parse_socks5_proxy leaks raw ValueError on bad port -> uncaught -> whole-pool crash (breaks Invariant 3 / AC3); (2) revive_slot hardcoded proxy=None + _Account stored no proxy -> revived slot egresses bare IP (Scope explicitly required threading proxy into revive)"
    fix: "(1) try/except ValueError around parsed.port -> InvalidProxyError (credential-free); (2) store proxy on _Account in from_sessions, thread account.proxy through revive_slot; also percent-decode userinfo (LOW) + enumerate input index in skip warning (LOW)"

## Details

### Implementation (do, TDD)
- New domain error `InvalidProxyError(PoolConfigError)` (errors.py) — a malformed proxy for ONE slot, skipped not crashed.
- Constants: `SOCKS5_DEFAULT_PORT=1080`, `SOCKS5_PROXY_TYPE=2` (telethon accepts int 2 == SOCKS5, confirmed in telethon `connection.py:79` backward-compat path — no PySocks/python-socks import needed), `POOL_SESSION_PROXY_MAX=512`.
- `client.py`: pure `parse_socks5_proxy(uri) -> (SOCKS5_PROXY_TYPE, host, port, True, user, pass)`; factory alias `(session, proxy=None)`; passes `proxy=tuple` to `TelegramClient` only when set (no-proxy path byte-identical).
- `pool_sessions.py`: `proxy: Mapped[str | None]` via `EncryptedString(POOL_SESSION_PROXY_MAX)`, nullable (Fernet at rest, like `session_string`).
- `account_pool.py`: `from_sessions(proxies=...)`, per-slot `InvalidProxyError` skip (index-only log), POOL_MIN/MAX re-validated on built count; `_Account.proxy` field; `revive_slot` threads `account.proxy` (IP affinity across re-mint).
- `pool_session_store.py`: `StoredSession.proxy` (repr=False, secret) carried by `active_sessions`/`find_active_by_tg_user_id`. `registry._union_pool_sessions` returns a 4-tuple with proxies; `_build_telegram_collector` passes `proxies=`. API/upsert untouched (out of scope).

### Verify evidence (G2)
- `make ci-fast` equivalent: ruff format `395 files already formatted`; ruff check `All checks passed!`; mypy `Success: no issues found in 189 source files`; collector unit suite **277 passed**; full non-integration **1248 passed**.
- Migration 0026 round-trip on LIVE Postgres: upgrade `0025 -> 0026` (proxy VARCHAR(512) NULL present), downgrade `0026 -> 0025` (proxy column absent, version 0025), upgrade again `0025 -> 0026`. revision="0026", down_revision="0025".
- Proxy passthrough behavioral: `test_proxy.py` — AC1 (slot0 gets proxy tuple, slot1 None), AC2 (proxies=None → factory gets None, byte-identical), AC3 (bad proxy incl. bad-PORT skips exactly one slot, pool still builds), parse valid/no-auth/missing-port/invalid/percent-encoded.
- Ciphertext at rest (live DB): raw `SELECT proxy` = `gAAAAAB...` Fernet token, != plaintext; ORM/`active_sessions` decrypts to `socks5://proxyuser:proxypass@proxy.example.com:1080`.

### Review + security
- Review (opus) flagged 2 HIGH: (1) raw `ValueError` on bad port crashed whole pool; (2) `revive_slot` dropped proxy. Both FIXED (debug run 1) + behaviorally tested. 2 LOW (percent-decode userinfo, enumerate input index) also fixed.
- Security (opus): all 5 invariants hold — proxy encrypted at rest, never logged (only scheme echoed in errors / slot-index in skip warning), never in Redis/API (StoredSession.proxy repr=False, AccountStatus has no proxy field, API untouched), no injection/SSRF, per-slot fail-closed + pool fail-open.

### Decisions
- `SOCKS5_PROXY_TYPE=2` literal (not `socks.SOCKS5`) because neither PySocks nor python-socks is installed; telethon natively accepts the int — documented in code.
- Proxy NOT wired into the API/upsert in this task (Scope excludes API/frontend); proxy column is set out-of-band (DB/ops) for now. A future task can add the write path + revive-signal proxy.
