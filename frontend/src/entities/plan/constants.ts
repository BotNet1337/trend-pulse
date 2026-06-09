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
 * these mirror overview §6 / backend billing/plans.py (Pro $19, Team $79).
 */
export const PLAN_PRICE_USD: Readonly<Record<PlanId, number>> = {
  [PLAN_FREE]: 0,
  [PLAN_PRO]: 19,
  [PLAN_TEAM]: 79,
};

/** Max watchlists per plan. */
export const PLAN_MAX_WATCHLISTS: Readonly<Record<PlanId, number | null>> = {
  [PLAN_FREE]: 3,
  [PLAN_PRO]: 25,
  [PLAN_TEAM]: null, // unlimited
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

/** Human-readable plan display names. */
export const PLAN_DISPLAY_NAME: Readonly<Record<PlanId, string>> = {
  [PLAN_FREE]: 'Free',
  [PLAN_PRO]: 'Pro',
  [PLAN_TEAM]: 'Team',
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
