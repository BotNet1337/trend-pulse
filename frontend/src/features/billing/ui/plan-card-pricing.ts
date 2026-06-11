/**
 * Pure pricing view-model for one plan card under a selected billing period
 * (TASK-047). Lives in its own module (not plan-comparison.tsx) so the component
 * file only exports components (react-refresh rule) and the helper stays
 * unit-testable without rendering.
 */

import {
  BILLING_PERIOD_BILLED_NOTE,
  BILLING_PERIOD_PRICE_SUFFIX,
  BILLING_PERIOD_SAVINGS_NOTE,
  PLAN_PERIOD_PRICE_USD,
  type BillingPeriodId,
  type PlanId,
} from '@/entities/plan';

export interface PlanCardPricing {
  /** Display amount in USD for the plan/period — equals the period constant. */
  amountUsd: number;
  /** Price suffix, e.g. "/year". */
  suffix: string;
  /** Savings copy ("Save ~20%") or null for month. */
  savingsNote: string | null;
  /** Billing cadence copy ("Billed yearly") or null for month. */
  billedNote: string | null;
}

/**
 * Build the pricing view-model for a plan card. The card/button amount MUST
 * equal the period constant — the authoritative charge amount is still the
 * backend InvoiceResponse (invariant TASK-049).
 */
export const planCardPricing = (plan: PlanId, period: BillingPeriodId): PlanCardPricing => ({
  amountUsd: PLAN_PERIOD_PRICE_USD[plan][period],
  suffix: BILLING_PERIOD_PRICE_SUFFIX[period],
  savingsNote: BILLING_PERIOD_SAVINGS_NOTE[period],
  billedNote: BILLING_PERIOD_BILLED_NOTE[period],
});
