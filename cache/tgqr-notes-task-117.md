# TASK-117 notes — admin TG pool QR-login + connection-status UI (for TEST/review)

Branch `feat/tg-qr-login`. Frontend FSD feature, mirrors `admin-metrics`.

## Route + nav
- Path constant: `paths.admin.pool` = **`/admin/pool`** (browser URL; the SPA route).
- Registered in `frontend/src/app/router/router.ts` as `adminPoolRoute` under
  `protectedContentRoute` (AuthGuard). No superuser check in the router — the page
  renders a 404-clone for non-superusers (`shouldShowPoolAdminNotFound`) and the
  REAL gate is backend `current_superuser` (403). Same pattern as admin-metrics.
- Nav entry: superuser-gated "TG pool (admin)" link in the account dropdown menu
  (`frontend/src/pages/index/app-shell.tsx`, `AccountMenu`, `isSuperuser` prop).
  Admin links live in that menu, not the main appbar (matches existing admin UX).

## Components
- `features/pool-admin/ui/pool-health-table.tsx` `PoolHealthTable` — props `{health}`.
  Per-account row: index, state badge (Connected/Cooling/Quarantined →
  fs-badge--success/warning/danger), cooldown (m:ss) only for cooling,
  last_error_reason only for quarantined. Aggregates line + Degraded badge.
  `stale` → status banner (`data-testid="pool-stale-banner"`), accounts hidden.
  Empty (non-stale, 0 accounts) → "No pool accounts." `fs-*`/`fs-table` styling.
- `features/pool-admin/ui/qr-login-dialog.tsx` `QrLoginDialog` — props `{open,onClose}`.
  Uses shared `ModalDialog` + `Button` (Tailwind), `QRCodeSVG` from `qrcode.react`.
  On open: POST start (auto, once). Renders `qr_url` as QR + live status. Polls 2s.
  success → copy-to-clipboard session string (`copyToClipboard` shared lib) + the
  "Add to TELEGRAM_POOL_SESSIONS in the vault and redeploy. It is shown only once."
  note. expired/password_needed/error → specific `qrStatusMessage(status, reason)`
  + "Regenerate QR". start 503 → "not configured", 429 → "too many concurrent".
- `pages/admin/pool.tsx` `AdminPoolPage` — head (Refresh + Add account), loading/
  error, table, dialog.

## Data layer
- `api.ts`: `startQrLogin()` POST `/pool-admin/qr-login/start`, `pollQrLogin(token)`
  GET `/pool-admin/qr-login/{token}` (token url-encoded), `getPoolHealth()` GET
  `/pool-admin/pool-health`. baseURL `/api/v1` (client). Types from gen.types.
- `queries.ts`: `usePoolHealth(enabled)` key `['admin','pool-health']`, 15s refetch,
  retry:false; `useQrLoginStart()`; `useQrLoginPoll(token|null)` key
  `['admin','qr-login',token]`, refetchInterval fn 2s while non-terminal → false.
- `lib.ts` (pure, unit-tested): literal unions + narrowers (state/status, unknown
  → fail-safe), `isTerminalQrStatus`, `qrStatusMessage`, `formatCooldown`,
  `accountStateLabel`/`accountStateBadgeVariant`, `shouldShowPoolAdminNotFound`.

## Security invariant (5.5 gate)
- `session_string` shown ONCE on success, copy-to-clipboard only, NEVER console.*'d,
  never persisted. Poll query is `removeQueries`'d on dialog close → secret does
  not linger in the RQ cache. (Mirrors api-keys created-key-modal discipline.)

## Gotchas
- OpenAPI types `state`/`status` as plain `string` (Pydantic enums dumped as bare
  string) → narrowers live in lib.ts; don't expect `gen.types` literal unions.
- OpenAPI regen: `make gen-openapi` (= `GEN_DUMP_ENV uv run --directory backend
  python scripts/dump_openapi.py`, writes directly to frontend openapi.json) then
  `npm run gen:api`. Diff additive only (271/0 openapi, 240/0 types) → no drift.
- New dep `qrcode.react@^4.2.0` (exports `QRCodeSVG`, `QRCodeCanvas`).

## Verify state (TEST stage to finish)
- tsc -b clean, eslint clean, vitest 303/303 (17 new in tests/unit/admin/pool-admin.spec.ts),
  `npm run build` green. Live `/admin/pool` render needs the running backend stack
  (start→QR→poll→success path) — deferred to TEST. node_modules installed in worktree.
