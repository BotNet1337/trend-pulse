/**
 * Pure view-model helpers for the admin money dashboard (TASK-063).
 *
 * Kept free of React so they are unit-testable in the node vitest environment
 * (project convention — no @testing-library/react).
 */

/** Decimal fields (`mrr`, `avg_check_30d`) arrive as JSON strings from FastAPI. */
const EM_DASH = '—';

/** Retention copy for `repeat_payment_rate = null` — no data ≠ 0% (invariant). */
export const NO_RETENTION_DATA_LABEL = 'No matured users yet';

/** Format a Decimal-as-string as `$X.XX`; non-numeric input → em dash. */
export function formatUsd(value: string): string {
  if (value.trim() === '') return EM_DASH;
  const parsed = Number(value);
  if (Number.isNaN(parsed)) return EM_DASH;
  return `$${parsed.toFixed(2)}`;
}

/** Format a 0..1 fraction as a percentage with one decimal place. */
export function formatPercent(fraction: number): string {
  return `${(fraction * 100).toFixed(1)}%`;
}

/**
 * Retention label: `null` means "no matured users yet" (no data), which must
 * be visually distinct from a real measured `0` → '0.0%'.
 */
export function formatRetention(rate: number | null): string {
  if (rate === null) return NO_RETENTION_DATA_LABEL;
  return formatPercent(rate);
}

/** Stable (alphabetical) plan → count entries for deterministic rendering. */
export function planEntries(byPlan: Record<string, number>): Array<[string, number]> {
  return Object.entries(byPlan).sort(([a], [b]) => a.localeCompare(b));
}

/** Total active paid subscriptions across all plans (0 when dict is empty). */
export function totalActiveSubscriptions(byPlan: Record<string, number>): number {
  return Object.values(byPlan).reduce((sum, count) => sum + count, 0);
}

/** Minimal slice of CurrentUser the guard decision needs. */
export interface AdminGuardUser {
  is_superuser: boolean;
}

/**
 * Decide whether /admin/metrics must render the not-found state.
 *
 * - `undefined` user → still loading, no decision yet.
 * - `null` user → unauthenticated; AuthGuard owns the sign-in redirect.
 * - non-superuser → not-found (no existence leak, same markup as a real 404).
 * - superuser + API 403 → not-found (stale flag race: rights were revoked).
 * - other API errors (e.g. 500) are NOT a not-found — caller shows error state.
 *
 * This is UX only — the real protection is `current_superuser` on the server.
 */
export function shouldShowAdminNotFound(
  user: AdminGuardUser | null | undefined,
  errorStatus: number | undefined,
): boolean {
  if (user === null || user === undefined) return false;
  if (!user.is_superuser) return true;
  return errorStatus === 403;
}
