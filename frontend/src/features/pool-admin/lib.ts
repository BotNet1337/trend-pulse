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
 * Non-secret display label for an account (the masked id / `@username` from the store).
 * Falls back to `account #<index>` when the backend has no identity for the slot (an
 * env-only / pre-identity account) so every row is still nameable (TASK-120).
 */
export function accountLabel(
  displayLabel: string | null | undefined,
  index: number,
): string {
  const trimmed = displayLabel?.trim();
  return trimmed ? trimmed : `account #${index}`;
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
      return `Re-connected${named} — the same account is back. The pool will show it Connected within ~one collect cycle.`;
    case 'add':
      return `Added${named} as a new pool account. It will appear in the table within ~one collect cycle.`;
    case null:
      return 'Logged in. Copy the session string below as a backup.';
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
