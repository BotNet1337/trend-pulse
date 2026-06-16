# TASK-120 notes — revive API + UI (identity, REVIVE/ADD outcome, in-place status flip)

Branch `feat/pool-health-revive`, baseline `98bd84c` (HEAD includes TASK-118 + TASK-119).
Final story of EPIC-POOL-HEALTH-REVIVE — the thin API/UI surface over TASK-119's store + revive
and TASK-118's honesty model. NO new mechanics: it persists on success, classifies, and tells the truth.

## API — QR poll SUCCESS persists + classifies (`backend/src/api/routes/pool_admin.py`)
- `poll_qr_login` is now `async` with two new deps: `get_pool_admin_db` (sync `Session` via
  `storage.database.get_session`, commit-on-success UoW) and `get_pool_revive_redis` (short-lived
  Redis behind the new narrow `_ReviveRedisLike`/`_ReviveRedisAdapter` seam — `set`/`srem`/`close`,
  one `cast` each, no `Any`/ignore). On a SUCCESS poll carrying a full identity it calls
  `_persist_qr_success`:
  - `upsert_revive_or_add(db, tg_user_id=, session_string=, display_label=, pool_max=POOL_MAX,
    env_floor_size=len(set(telegram_pool_sessions(settings))))` run in a threadpool (sync store).
    `env_floor_size` reserves room for env slots so DB rows + env can never exceed POOL_MAX (TASK-119 fix).
  - REVIVE → write the non-secret revive-signal `{tg_user_id, fingerprint}` to
    `POOL_REVIVE_SIGNAL_REDIS_KEY` (TTL `POOL_REVIVE_SIGNAL_TTL_SECONDS`) so the worker swaps the live
    slot next tick, AND `srem` the OLD `previous_fingerprint` from `pool:quarantined_fingerprints`.
    Both best-effort / fail-open (class-name-only log). ADD → no signal (next full build picks it up).
  - Over-cap ADD → `PoolCapacityExceededError` → HTTP 409 `_POOL_FULL_MESSAGE` ("revoke an account
    first"); the minted `session_string` copy-field is STILL returned (DR floor preserved, no secret
    in the 409 body). Any OTHER store/DB error → copy-field preserved, NO `outcome`, logged class-name-only.
  - Idempotent: the store upsert is keyed by `tg_user_id`; a repeated SUCCESS poll (polling is a loop)
    revives in place, never dupes.
- `QRLoginPollResponse` += `tg_user_id`/`display_label`/`outcome` (non-secret, SUCCESS-only).
  `session_string` copy-field UNCHANGED (owner-default keep-for-DR; one-line removal if dropped later).
- `PoolHealthAccount` += `display_label`/`tg_user_id` (null for env-only slot). `_PoolHealthSnapshot`
  validates them via `accounts: list[PoolHealthAccount]` — no snapshot-writer change needed (the writer
  already `asdict`s the AccountStatus which now carries them). `extra="forbid"` on responses kept;
  superuser gate unchanged; secrets (session string) NEVER logged, only the existing copy-field.

## Identity carried through worker → snapshot (additive, no secret)
- `account_pool.py`: `_Account`/`AccountStatus` += `display_label: str | None`; `from_sessions(...
  display_labels=)`, `account_statuses()` surfaces it, `revive_slot(... display_label=)` refreshes it.
  `tg_user_id` was already on `_Account` (TASK-119) — now also surfaced in `AccountStatus`.
- `registry.py`: `_union_pool_sessions` → 3-tuple `(sessions, tg_user_ids, display_labels)`; DB rows
  carry their `StoredSession.display_label`, env slots None; passed to `from_sessions`.
- `reader.py`: revive-apply passes `stored.display_label` into `revive_slot`.

## Frontend — "Add / re-connect account" UX (`frontend/src/features/pool-admin/`)
- `lib.ts`: `ReviveOutcome='revive'|'add'`; `asReviveOutcome` (unknown/absent → null = neutral copy,
  no wrong claim); `accountLabel(label,index)` → trimmed label or `account #<index>`;
  `reviveSuccessMessage(outcome,label)` → distinct "Re-connected <label> — same account…" vs
  "Added <label> as a new pool account…", neutral "Logged in…" when outcome null.
- `queries.ts`: `invalidatePoolHealth(queryClient)` invalidates exactly `POOL_HEALTH_QUERY_KEY`.
- `qr-login-dialog.tsx`: title "Add / re-connect account"; SUCCESS shows outcome message + identity
  (`data-testid=qr-success-message[data-outcome]`, `qr-success-identity`); a `useEffect` on
  `status==='success'` invalidates pool-health so the table refetches and the row flips to Connected
  within ~1 cycle — HONEST, NO fake optimistic flip. Vault note re-worded: account already persisted,
  the session string is a one-time DR backup.
- `pool-health-table.tsx`: new "Account" column (`accountLabel(account.display_label, index)`).
- `pages/admin/pool.tsx`: button relabeled "Add / re-connect account".
- OpenAPI regenerated (`make gen-openapi gen-types`) → `gen.types.ts` typed (no hand-rolled shapes, no `any`).

## Invariants held
- Only secret ever returned = the existing one-shot `session_string` copy-field (superuser, HTTPS,
  never logged). Identity fields (masked id / @username / numeric id) are non-secret. The revive-signal
  + the SREM'd fingerprint carry NO session string. The API never mutates the live pool — it persists +
  signals; the worker applies the swap (TASK-119). Persistence side effect idempotent by `tg_user_id`.

## Gate evidence
- Backend `make fmt`/`lint`/`typecheck` green (mypy strict, 189 files, no Any/ignore).
- `make test` = 1152 passed, 307 deselected. Updated 4 additive-shape tests:
  test_pool_health (account key set + null identity), test_reader_revive (revive_slot kw),
  test_registry x2 (3-tuple union), test_pool_session_store (3-tuple union + label).
- Integration on throwaway `pgvector/pgvector:pg16` (127.0.0.1:55440, user=postgres): pool_admin(24) +
  pool_session_store + at_rest_encryption + migrations = 38 passed; container torn down after.
- Frontend `npm install`, `npx tsc -b`, `npm run lint`, `npx vitest run` = 315 passed (revive.spec.ts +9).

## Endpoint contract (the new surface)
- `GET /pool-admin/qr-login/{token}` SUCCESS body (superuser): `{status:"success", expires_at,
  session_string (secret, DR floor), reason:null, tg_user_id:int, display_label:str,
  outcome:"revive"|"add"}`. Over-cap ADD → 409 `{error:_POOL_FULL_MESSAGE}` (session copy-field still
  in the 4xx? — no: 409 has no body session; the copy-field is only on the 200 SUCCESS path; the
  store error path returns the 200 SUCCESS body with copy-field and no outcome).
- `GET /pool-admin/pool-health` accounts[] += `display_label:str|null`, `tg_user_id:int|null`.
