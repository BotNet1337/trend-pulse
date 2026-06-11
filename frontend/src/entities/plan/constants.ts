/**
 * Plan tier constants for TrendPulse billing (TASK-017, overview §6).
 *
 * Source of truth for plan names, prices, and feature limits.
 * Numbers come from the product overview §6 — DO NOT inline these in components.
 *
 * Backend is the authoritative source for enforcement; these constants are
 * used for display / comparison UI only.
 */

/** Plan identifier values — match `users.plan` column values on the backend. */
export const PLAN_FREE = 'free' as const;
export const PLAN_PRO = 'pro' as const;
export const PLAN_TEAM = 'team' as const;

export type PlanId = typeof PLAN_FREE | typeof PLAN_PRO | typeof PLAN_TEAM;

/**
 * Monthly prices in USD — for plan comparison display only. The authoritative
 * charge amount comes from the backend InvoiceResponse (POST /billing/invoice);
 * these mirror overview §6 / backend billing/plans.py (TASK-049: Pro $29, Trader/Team $99).
 */
export const PLAN_PRICE_USD: Readonly<Record<PlanId, number>> = {
  [PLAN_FREE]: 0,
  [PLAN_PRO]: 29,
  [PLAN_TEAM]: 99,
};

/**
 * Max own channels (watchlists) per plan — synced to backend CHANNELS limits (TASK-049).
 * Free=0: own channels are blocked; Free value prop is curated packs + delayed alerts.
 * Pro=100, Trader/Team=500.
 *
 * Note: variable name kept as PLAN_MAX_WATCHLISTS (not renamed to PLAN_MAX_CHANNELS)
 * because there are only 2 src call-sites — renaming would be pure churn (TASK-049 scope).
 */
export const PLAN_MAX_WATCHLISTS: Readonly<Record<PlanId, number>> = {
  [PLAN_FREE]: 0,
  [PLAN_PRO]: 100,
  [PLAN_TEAM]: 500,
};

/** Alert history window in days (null = none). 0 = no history. */
export const PLAN_HISTORY_DAYS: Readonly<Record<PlanId, number>> = {
  [PLAN_FREE]: 0,
  [PLAN_PRO]: 30,
  [PLAN_TEAM]: 90,
};

/** Whether the plan supports webhook delivery. */
export const PLAN_WEBHOOK_DELIVERY: Readonly<Record<PlanId, boolean>> = {
  [PLAN_FREE]: false,
  [PLAN_PRO]: true,
  [PLAN_TEAM]: true,
};

/**
 * Human-readable plan display names.
 * TASK-049: team tier displays as "Trader" (enum value "team" and DB column unchanged).
 */
export const PLAN_DISPLAY_NAME: Readonly<Record<PlanId, string>> = {
  [PLAN_FREE]: 'Free',
  [PLAN_PRO]: 'Pro',
  [PLAN_TEAM]: 'Trader',
};

/** Ordered list of plan tiers (lowest → highest). */
export const PLAN_TIERS: ReadonlyArray<PlanId> = [PLAN_FREE, PLAN_PRO, PLAN_TEAM];

/**
 * Returns true if `current` is at least `required` tier.
 * Used by the UI to decide whether to show upsell prompts.
 */
export const isPlanAtLeast = (current: PlanId, required: PlanId): boolean => {
  const tierIndex = PLAN_TIERS.indexOf(current);
  const requiredIndex = PLAN_TIERS.indexOf(required);
  return tierIndex >= requiredIndex;
};
