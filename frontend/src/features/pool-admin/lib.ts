/**
 * Pure view-model helpers for the TG pool admin UI (TASK-117).
 *
 * Kept free of React so they are unit-testable in the node vitest environment
 * (project convention — see admin-metrics/lib.ts, no @testing-library/react).
 *
 * The OpenAPI schema types `state`/`status` as plain `string`, so the literal
 * unions and the terminal-status set live here (single source of truth for the
 * QR flow state machine and the pool-health badges).
 */

/**
 * Per-account pool state (backend `PoolHealthAccount.state`).
 *
 * `failing` (TASK-118) means the account is CONNECTED but its reads persistently fail
 * (the swallowed "wrong session ID" class) — distinct from `quarantined` (a dead
 * session, permanently evicted) and observational only on the backend.
 */
export type AccountState = 'healthy' | 'cooling' | 'quarantined' | 'failing';

/**
 * Per-account provenance (backend `PoolHealthAccount.source`, TASK-130):
 * `manual` (the owner onboarded it via QR) vs `auto` (the account-factory promoted it).
 * The OpenAPI schema types it as a plain `string`, so the literal union lives here.
 */
export type AccountSource = 'manual' | 'auto';

/** Narrow the backend `string` source to the known union (unknown/absent → 'manual'). */
export function asAccountSource(raw: string | null | undefined): AccountSource {
  return raw === 'auto' ? 'auto' : 'manual';
}

/** Human label for an account source badge. */
export function accountSourceLabel(source: AccountSource): string {
  switch (source) {
    case 'manual':
      return 'Manual';
    case 'auto':
      return 'Auto';
  }
}

/**
 * Badge variant class suffix for a source (maps to existing `fs-badge--*` modifiers):
 * `auto` → `info` (an accent, machine-added), `manual` → `neutral` (the quiet default).
 */
export function accountSourceBadgeVariant(source: AccountSource): 'info' | 'neutral' {
  switch (source) {
    case 'auto':
      return 'info';
    case 'manual':
      return 'neutral';
  }
}

/**
 * Persistence outcome after a successful QR login (backend
 * `QRLoginPollResponse.outcome`): `revive` re-connected an EXISTING account (the same
 * row flips back to Connected within ~one collect cycle), `add` registered a NEW
 * account. The store decides by `tg_user_id`; the UI only surfaces it (TASK-120).
 */
export type ReviveOutcome = 'revive' | 'add';

/** QR-login poll status (backend `QRLoginPollResponse.status`). */
export type QrLoginStatus =
  | 'pending'
  | 'success'
  | 'expired'
  | 'password_needed'
  | 'error';

/** Statuses after which polling MUST stop (nothing more will change). */
const TERMINAL_QR_STATUSES: ReadonlySet<QrLoginStatus> = new Set<QrLoginStatus>([
  'success',
  'expired',
  'password_needed',
  'error',
]);

/** True once the QR login has reached a terminal status (stop polling). */
export function isTerminalQrStatus(status: QrLoginStatus): boolean {
  return TERMINAL_QR_STATUSES.has(status);
}

/** Narrow the backend `string` status to the known union (unknown → 'error'). */
export function asQrLoginStatus(raw: string): QrLoginStatus {
  switch (raw) {
    case 'pending':
    case 'success':
    case 'expired':
    case 'password_needed':
    case 'error':
      return raw;
    default:
      return 'error';
  }
}

/** Narrow the backend `string` state to the known union (unknown → 'quarantined'). */
export function asAccountState(raw: string): AccountState {
  switch (raw) {
    case 'healthy':
    case 'cooling':
    case 'quarantined':
    case 'failing':
      return raw;
    default:
      return 'quarantined';
  }
}

/** Human label for an account state badge. */
export function accountStateLabel(state: AccountState): string {
  switch (state) {
    case 'healthy':
      return 'Connected';
    case 'cooling':
      return 'Cooling';
    case 'quarantined':
      return 'Quarantined';
    case 'failing':
      return 'Failing';
  }
}

/** Badge variant class suffix (maps to the project's `fs-badge--*` modifiers). */
export function accountStateBadgeVariant(
  state: AccountState,
): 'success' | 'warning' | 'danger' {
  switch (state) {
    case 'healthy':
      return 'success';
    case 'cooling':
      return 'warning';
    // `failing` is a soft alert (connected-but-not-reading) — `warning`, distinct from
    // the `danger` of a dead `quarantined` session (TASK-118).
    case 'failing':
      return 'warning';
    case 'quarantined':
      return 'danger';
  }
}

/**
 * Human, non-secret status line shown in the QR dialog. The `reason` (an error
 * CLASS NAME or a short note from the backend — never secret-bearing) is woven
 * in for password_needed/error so the user sees the SPECIFIC cause, not a
 * generic failure (AC: "show the specific reason, not a generic error").
 */
export function qrStatusMessage(status: QrLoginStatus, reason: string | null): string {
  switch (status) {
    case 'pending':
      return 'Waiting for you to scan and authorize the code in Telegram…';
    case 'success':
      return 'Logged in. Copy the session string below.';
    case 'expired':
      return 'The QR code expired before it was authorized. Regenerate it to try again.';
    case 'password_needed':
      return reason
        ? `This account has a 2FA cloud password, which QR-only login can't complete (${reason}).`
        : "This account has a 2FA cloud password, which QR-only login can't complete.";
    case 'error':
      return reason
        ? `Login failed: ${reason}. Regenerate the QR code to try again.`
        : 'Login failed. Regenerate the QR code to try again.';
  }
}

/**
 * Narrow the backend `string` outcome to the known union, or null when absent /
 * unknown (the field is present only on a SUCCESS that was persisted). An unknown
 * value collapses to null so the UI shows the neutral success copy, not a wrong claim.
 */
export function asReviveOutcome(raw: string | null | undefined): ReviveOutcome | null {
  return raw === 'revive' || raw === 'add' ? raw : null;
}

/**
 * Non-secret PRIMARY identity for an account row: the `@username` (`display_label` from
 * `get_me()`, e.g. "@hart_1337"). Falls back to `#<index>` only when the backend has no
 * identity for the slot (an env-only / pre-identity account) so every row is still
 * nameable. The headline is the username; the numeric `index` is a muted secondary detail
 * shown separately in the table.
 */
export function accountLabel(
  displayLabel: string | null | undefined,
  index: number,
): string {
  const trimmed = displayLabel?.trim();
  return trimmed ? trimmed : `#${index}`;
}

/**
 * Known per-account error CLASSES → a short, human RU explanation so the owner can react.
 * Keys are the Telethon exception class names the backend records as `last_error_reason`
 * (CLASS NAME only — never a secret/message). Maintained as a single source of truth.
 */
const KNOWN_ERROR_EXPLANATIONS: Readonly<Record<string, string>> = {
  SecurityError:
    'Конфликт сессии (wrong session ID) — сессия используется параллельно, переподключи через QR',
  AuthKeyDuplicatedError: 'Сессия мертва — перевыпусти',
  AuthKeyError: 'Сессия мертва — перевыпусти',
  SessionRevokedError: 'Сессия мертва — перевыпусти',
  UserDeactivatedError: 'Сессия мертва — перевыпусти',
  FLOOD_WAIT: 'FLOOD_WAIT — временный лимит Telegram',
};

/**
 * Human, non-secret explanation for an account's `last_error_reason` (the recorded error
 * CLASS NAME, never a secret). Returns a readable RU line for a known class, the RAW class
 * name for an unknown one (never guess), or null when there is no reason to show. Pure +
 * unit-tested — never logs.
 */
export function accountErrorExplanation(reason: string | null | undefined): string | null {
  const trimmed = reason?.trim();
  if (!trimmed) return null;
  return KNOWN_ERROR_EXPLANATIONS[trimmed] ?? trimmed;
}

/**
 * Human, non-secret success line for the QR dialog after persistence (TASK-120).
 *
 * Makes "тот же аккаунт имеет другой статус" obvious: a `revive` says the SAME account
 * was re-connected and its row will flip back to Connected within ~one collect cycle; an
 * `add` says a NEW account was registered. A null outcome (persistence not reached, e.g.
 * a store error with the copy-field preserved) yields a neutral success line.
 */
export function reviveSuccessMessage(
  outcome: ReviveOutcome | null,
  displayLabel: string | null | undefined,
): string {
  const label = displayLabel?.trim();
  const named = label ? ` ${label}` : '';
  switch (outcome) {
    case 'revive':
      return `Re-connected${named} — the same account is back. It is picked up automatically within ~one minute (no restart).`;
    case 'add':
      return `Added${named} — the account is picked up automatically within ~one minute (no restart).`;
    case null:
      // Persistence not reached (e.g. a store error); the session string backup below is
      // the fallback the admin can still vault. No "copy this" headline either way.
      return 'Logged in. The account could not be auto-persisted — use the backup below.';
  }
}

/** Format a cooldown in whole seconds as `m:ss` (or `0:ss`); null/≤0 → null. */
export function formatCooldown(seconds: number | null | undefined): string | null {
  if (seconds === null || seconds === undefined) return null;
  const total = Math.max(0, Math.ceil(seconds));
  if (total === 0) return null;
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

// ─── TASK-136: Account-factory view-model helpers ─────────────────────────────

/**
 * Per-account factory lifecycle state (backend `FACTORY_STATES` from factory/constants.py).
 *
 * States: purchased → registered → probation → promoted (happy path)
 *         failed / banned (terminal off-ramps, reachable from any non-terminal state)
 *
 * The backend `state` field is a plain string; this union + narrowing function
 * are the single source of truth on the frontend.
 */
export type FactoryAccountState =
  | 'purchased'
  | 'registered'
  | 'probation'
  | 'promoted'
  | 'failed'
  | 'banned';

/** Narrow the backend `string` state to the known union (unknown → 'failed', fail-safe). */
export function asFactoryAccountState(raw: string): FactoryAccountState {
  switch (raw) {
    case 'purchased':
    case 'registered':
    case 'probation':
    case 'promoted':
    case 'failed':
    case 'banned':
      return raw;
    default:
      return 'failed';
  }
}

/** Human label for a factory account state badge. */
export function factoryStateLabel(state: FactoryAccountState): string {
  switch (state) {
    case 'purchased':
      return 'Purchased';
    case 'registered':
      return 'Registered';
    case 'probation':
      return 'Probation';
    case 'promoted':
      return 'Promoted';
    case 'failed':
      return 'Failed';
    case 'banned':
      return 'Banned';
  }
}

/**
 * Badge variant class suffix for a factory account state (maps to existing `fs-badge--*` modifiers):
 * - promoted → success (happy terminal)
 * - probation → info (waiting/warmup)
 * - failed / banned → danger (terminal failure)
 * - purchased / registered → warning (in-progress, not yet stable)
 */
export function factoryStateBadgeVariant(
  state: FactoryAccountState,
): 'success' | 'warning' | 'danger' | 'info' {
  switch (state) {
    case 'promoted':
      return 'success';
    case 'probation':
      return 'info';
    case 'failed':
    case 'banned':
      return 'danger';
    case 'purchased':
    case 'registered':
      return 'warning';
  }
}

/**
 * Human probation countdown from an ISO timestamp to a human string like `"3d 4h"`, `"5h 30m"`,
 * or `"42m"`. Returns `null` when `probationUntil` is null or already elapsed.
 *
 * `now` is injectable for deterministic unit tests; defaults to `new Date()`.
 */
export function formatProbationCountdown(
  probationUntil: string | null,
  now: Date = new Date(),
): string | null {
  if (!probationUntil) return null;

  const untilMs = new Date(probationUntil).getTime();
  const diffMs = untilMs - now.getTime();

  if (diffMs <= 0) return null;

  const totalMinutes = Math.floor(diffMs / (60 * 1000));
  const days = Math.floor(totalMinutes / (24 * 60));
  const hours = Math.floor((totalMinutes % (24 * 60)) / 60);
  const minutes = totalMinutes % 60;

  if (days > 0) {
    return hours > 0 ? `${days}d ${hours}h` : `${days}d`;
  }
  if (hours > 0) {
    return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
  }
  return `${minutes}m`;
}

// ─── TASK-136: Register-button decision helpers ────────────────────────────────

/**
 * Pure helper: should the "Register account" factory button be disabled?
 * True when budget is not yet loaded (undefined) OR the factory provider is not configured
 * (enabled === false). The mutating endpoints return 503 when provider is unset.
 */
export function isFactoryRegisterDisabled(budget: { enabled: boolean } | undefined): boolean {
  if (budget === undefined) return true;
  return !budget.enabled;
}

/**
 * Tooltip text for the disabled "Register account" button.
 * Rendered as the `title` attribute on the button element.
 */
export function factoryRegisterDisabledTooltip(): string {
  return 'Account factory is disabled (no provider configured)';
}

/** Minimal slice of CurrentUser the page's superuser gate needs. */
export interface PoolAdminGuardUser {
  is_superuser: boolean;
}

/**
 * Decide whether /admin/pool must render the not-found state (mirrors the
 * admin-metrics guard — no existence leak for non-superusers; a racy 403 also
 * collapses into not-found). UX only — the real gate is `current_superuser`.
 */
export function shouldShowPoolAdminNotFound(
  user: PoolAdminGuardUser | null | undefined,
  errorStatus: number | undefined,
): boolean {
  if (user === null || user === undefined) return false;
  if (!user.is_superuser) return true;
  return errorStatus === 403;
}
