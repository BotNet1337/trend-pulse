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

/** Per-account pool state (backend `PoolHealthAccount.state`). */
export type AccountState = 'healthy' | 'cooling' | 'quarantined';

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
