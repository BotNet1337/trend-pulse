/**
 * PlanComparison — table/card view comparing Free / Pro / Trader tiers (TASK-017).
 *
 * TASK-049: updated feature copy per new price grid.
 * - Free: curated packs + delayed alerts (no "own channels" claim)
 * - Pro $29: own channels + real-time + webhook
 * - Trader $99 (internal: team): API keys + real-time + webhook + 90d history + 500 channels
 *
 * Numbers come from entities/plan constants — NOT inline magic numbers.
 */

import * as React from 'react';

import {
  PLAN_DISPLAY_NAME,
  PLAN_FREE,
  PLAN_HISTORY_DAYS,
  PLAN_MAX_WATCHLISTS,
  PLAN_PRICE_USD,
  PLAN_PRO,
  PLAN_TEAM,
  PLAN_TIERS,
  PLAN_WEBHOOK_DELIVERY,
  type PlanId,
} from '@/entities/plan';
import { Button } from '@/shared/components/button';

interface PlanComparisonProps {
  /** Current user plan from GET /users/me. */
  currentPlan: PlanId;
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
  onUpgrade,
  isUpgrading = false,
}) => {
  return (
    <div
      data-testid="plan-comparison"
      className="grid grid-cols-1 gap-4 sm:grid-cols-3"
    >
      {PLAN_TIERS.map((plan) => {
        const isCurrent = plan === currentPlan;
        const isFree = plan === PLAN_FREE;
        const price = PLAN_PRICE_USD[plan];
        const displayName = PLAN_DISPLAY_NAME[plan];
        const features = planFeatures(plan);

        return (
          <div
            key={plan}
            data-testid={`plan-card-${plan}`}
            className={[
              'flex flex-col gap-4 rounded-2xl border p-6',
              plan === PLAN_PRO
                ? 'border-indigo-400/60 bg-indigo-50/60 dark:bg-indigo-900/20'
                : 'border-border bg-background',
            ].join(' ')}
          >
            <div className="flex flex-col gap-1">
              <span className="text-xs font-mono uppercase tracking-widest text-muted-foreground">
                {displayName}
              </span>
              <div className="flex items-baseline gap-1">
                <span className="text-3xl font-bold">
                  {isFree ? 'Free' : `$${price}`}
                </span>
                {!isFree && (
                  <span className="text-sm text-muted-foreground">/month</span>
                )}
              </div>
            </div>

            <ul className="flex flex-col gap-2 text-sm flex-1">
              {features.map(({ label, enabled }) => (
                <li key={label} className="flex items-center gap-2">
                  <span
                    className={[
                      'w-4 text-center',
                      enabled ? 'text-green-600' : 'text-muted-foreground/40',
                    ].join(' ')}
                    aria-hidden="true"
                  >
                    {enabled ? '✓' : '✗'}
                  </span>
                  <span className={enabled ? '' : 'text-muted-foreground/60'}>
                    {label}
                  </span>
                </li>
              ))}
            </ul>

            {isCurrent ? (
              <div
                className="inline-flex h-10 items-center justify-center rounded-md border border-border bg-secondary/40 px-4 text-sm text-muted-foreground"
                aria-label={`Current plan: ${displayName}`}
              >
                Current plan
              </div>
            ) : isFree ? (
              <div className="h-10" />
            ) : (
              <Button
                type="button"
                variant={plan === PLAN_PRO ? 'default' : 'outline'}
                disabled={isUpgrading}
                onClick={() => onUpgrade(plan)}
                data-testid={`upgrade-button-${plan}`}
                className="w-full"
                aria-label={`Upgrade to ${displayName} — $${price}/month`}
              >
                {isUpgrading ? 'Processing…' : `Upgrade to ${displayName}`}
              </Button>
            )}
          </div>
        );
      })}
    </div>
  );
};
