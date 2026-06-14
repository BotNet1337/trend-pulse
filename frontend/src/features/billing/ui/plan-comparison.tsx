/**
 * PlanComparison — table/card view comparing Free / Pro / Trader tiers (TASK-017).
 *
 * TASK-049: updated feature copy per new price grid.
 * - Free: curated packs + delayed alerts (no "own channels" claim)
 * - Pro $29: own channels + real-time + webhook
 * - Trader $99 (internal: team): API keys + real-time + webhook + 90d history + 500 channels
 *
 * TASK-047: month/quarter/year period toggle. Paid cards show the per-period
 * price (quarter ~ -10%, year ~ -20%) with savings + billing-cadence copy.
 * The selected period is owned by the page (BillingPage) — this component is a
 * controlled view: `period` + `onPeriodChange` props.
 *
 * Numbers come from entities/plan constants — NOT inline magic numbers.
 */

import * as React from 'react';

import {
  BILLING_PERIODS,
  BILLING_PERIOD_LABEL,
  BILLING_PERIOD_SAVINGS_NOTE,
  PLAN_DISPLAY_NAME,
  PLAN_FREE,
  PLAN_HISTORY_DAYS,
  PLAN_MAX_WATCHLISTS,
  PLAN_PRO,
  PLAN_TEAM,
  PLAN_TIERS,
  PLAN_WEBHOOK_DELIVERY,
  type BillingPeriodId,
  type PlanId,
} from '@/entities/plan';
import { Button } from '@/shared/components/button';
import { planCardPricing } from './plan-card-pricing';

interface PlanComparisonProps {
  /** Current user plan from GET /users/me. */
  currentPlan: PlanId;
  /** Selected billing period (owned by the page — controlled component). */
  period: BillingPeriodId;
  /** Called when the user switches the billing period toggle. */
  onPeriodChange: (period: BillingPeriodId) => void;
  /** Called when user clicks Upgrade on a given plan tier. */
  onUpgrade: (plan: PlanId) => void;
  /** True while invoice creation is in-flight. */
  isUpgrading?: boolean;
}

const formatHistory = (days: number): string => {
  if (days === 0) return 'No history';
  return `${days} days`;
};

/** Feature rows shown per plan tier (TASK-049: only implemented features). */
const planFeatures = (plan: PlanId): ReadonlyArray<{ label: string; enabled: boolean }> => {
  const maxChannels = PLAN_MAX_WATCHLISTS[plan];
  const historyDays = PLAN_HISTORY_DAYS[plan];
  const webhookDelivery = PLAN_WEBHOOK_DELIVERY[plan];

  if (plan === PLAN_FREE) {
    return [
      { label: 'Curated packs (1 pack)', enabled: true },
      { label: 'Alerts delayed 30 min', enabled: true },
      { label: 'Real-time alerts', enabled: false },
      { label: 'Own channels', enabled: false },
      { label: 'Webhook delivery', enabled: false },
    ];
  }

  if (plan === PLAN_TEAM) {
    return [
      { label: `${maxChannels} channels`, enabled: true },
      { label: 'Real-time alerts', enabled: true },
      { label: `Alert history: ${formatHistory(historyDays)}`, enabled: true },
      { label: 'Webhook delivery', enabled: webhookDelivery },
      { label: 'API keys', enabled: true },
    ];
  }

  // Pro
  return [
    { label: `${maxChannels} channels`, enabled: true },
    { label: 'Real-time alerts', enabled: true },
    { label: `Alert history: ${formatHistory(historyDays)}`, enabled: true },
    { label: 'Webhook delivery', enabled: webhookDelivery },
    { label: 'API keys', enabled: false },
  ];
};

export const PlanComparison: React.FC<PlanComparisonProps> = ({
  currentPlan,
  period,
  onPeriodChange,
  onUpgrade,
  isUpgrading = false,
}) => {
  return (
    <div className="fs-stack">
      {/* Billing period toggle (TASK-047): affects paid cards only. */}
      <div className="plan-toggle-row">
        <div
          role="group"
          aria-label="Billing period"
          data-testid="billing-period-toggle"
          className="fs-segment"
        >
          {BILLING_PERIODS.map((p) => {
            const isSelected = p === period;
            const savings = BILLING_PERIOD_SAVINGS_NOTE[p];
            return (
              <button
                key={p}
                type="button"
                aria-pressed={isSelected}
                data-testid={`billing-period-${p}`}
                onClick={() => onPeriodChange(p)}
              >
                {BILLING_PERIOD_LABEL[p]}
                {savings ? <span className="save">{savings}</span> : null}
              </button>
            );
          })}
        </div>
      </div>

      <div
        data-testid="plan-comparison"
        className="fs-plans"
        aria-label="Plan comparison"
      >
        {PLAN_TIERS.map((plan) => {
          const isCurrent = plan === currentPlan;
          const isFree = plan === PLAN_FREE;
          const pricing = planCardPricing(plan, period);
          const displayName = PLAN_DISPLAY_NAME[plan];
          const features = planFeatures(plan);

          return (
            <article
              key={plan}
              data-testid={`plan-card-${plan}`}
              className={[
                'fs-card fs-plan',
                plan === PLAN_PRO ? 'fs-plan--featured' : '',
              ].join(' ').trim()}
            >
              {isCurrent && <span className="fs-plan__badge">Current plan</span>}

              <span className="text-xs font-mono uppercase tracking-widest text-muted-foreground">
                {displayName}
              </span>
              <div className="fs-plan__price-row">
                <span className="fs-plan__price">
                  {isFree ? 'Free' : `$${pricing.amountUsd}`}
                </span>
                {!isFree && <span className="fs-plan__period">{pricing.suffix}</span>}
              </div>
              {!isFree && (pricing.savingsNote || pricing.billedNote) ? (
                <p className="fs-plan__note">
                  {pricing.billedNote}
                  {pricing.savingsNote ? (
                    <span className="font-medium text-green-600"> · {pricing.savingsNote}</span>
                  ) : null}
                </p>
              ) : (
                <p className="fs-plan__note">&nbsp;</p>
              )}

              <ul className="fs-plan__features">
                {features.map(({ label, enabled }) => (
                  <li key={label} className={enabled ? '' : 'is-off'}>
                    {enabled ? (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <path d="M20 6 9 17l-5-5" />
                      </svg>
                    ) : (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <path d="M18 6 6 18M6 6l12 12" />
                      </svg>
                    )}
                    <span>{label}</span>
                  </li>
                ))}
              </ul>

              {isCurrent ? (
                <div className="plan-current" aria-label={`Current plan: ${displayName}`}>
                  Current plan
                </div>
              ) : isFree ? null : (
                <Button
                  type="button"
                  variant={plan === PLAN_PRO ? 'default' : 'outline'}
                  disabled={isUpgrading}
                  onClick={() => onUpgrade(plan)}
                  data-testid={`upgrade-button-${plan}`}
                  className="fs-btn--block"
                  aria-label={`Upgrade to ${displayName} — $${pricing.amountUsd}${pricing.suffix}`}
                >
                  {isUpgrading ? 'Processing…' : `Upgrade to ${displayName}`}
                </Button>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
};
