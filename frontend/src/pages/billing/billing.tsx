/**
 * BillingPage — /billing route (TASK-017, Epic C/C5).
 *
 * Shows plan comparison (Free/Pro/Team) and handles upgrade → crypto invoice.
 * INVARIANT: No Stripe. Only POST /billing/invoice (NOWPayments).
 * INVARIANT: plan data from GET /users/me (useCurrentUser), not hardcoded.
 */

import * as React from 'react';

import {
  type BillingPeriodId,
  type PlanId,
  PERIOD_MONTH,
  PLAN_FREE,
  PLAN_DISPLAY_NAME,
} from '@/entities/plan';
import { useCurrentUser } from '@/entities/viewer/model';
import { PlanComparison } from '@/features/billing/ui/plan-comparison';
import { InvoiceDisplay } from '@/features/billing/ui/invoice-display';
import { useCreateInvoice, type InvoiceResponse } from '@/features/billing/model';

export const BillingPage: React.FC = () => {
  const { data: currentUser, isLoading } = useCurrentUser();

  const [pendingInvoice, setPendingInvoice] = React.useState<InvoiceResponse | null>(null);
  // TASK-047: selected billing period (month default — matches the API default).
  const [period, setPeriod] = React.useState<BillingPeriodId>(PERIOD_MONTH);

  const createInvoiceMutation = useCreateInvoice({
    onSuccess: (invoice) => {
      setPendingInvoice(invoice);
    },
  });

  const handleUpgrade = (plan: PlanId) => {
    if (createInvoiceMutation.isPending) return;
    setPendingInvoice(null);
    createInvoiceMutation.mutate({ plan, period });
  };

  // Determine current plan — fall back to free if not loaded yet
  const rawPlan = currentUser?.plan ?? PLAN_FREE;
  // Normalise to PlanId (backend returns lowercase string matching the union)
  const currentPlan = rawPlan as PlanId;
  const currentPlanDisplay = PLAN_DISPLAY_NAME[currentPlan] ?? rawPlan;

  return (
    <main className="fs-main">
      <div className="fs-container">
          <div className="fs-page-head">
            <h1 className="fs-page-head__title">Plans &amp; billing</h1>
            {!isLoading && currentUser && (
              <p className="fs-page-head__sub">
                Current plan:{' '}
                <strong style={{ color: 'var(--fs-text)' }}>
                  {currentPlanDisplay}
                </strong>
              </p>
            )}
          </div>

          {/* Invoice display (shown after upgrade click) */}
          {pendingInvoice && (
            <div style={{ marginBottom: '1.5rem' }}>
              <InvoiceDisplay invoice={pendingInvoice} />
            </div>
          )}

          {/* Invoice error */}
          {createInvoiceMutation.isError && (
            <div role="alert" className="fs-banner fs-banner--danger" style={{ marginBottom: '1.5rem' }}>
              {createInvoiceMutation.error?.message ?? 'Failed to create invoice. Please try again.'}
            </div>
          )}

          {/* Plan comparison */}
          {isLoading ? (
            <div className="fs-center fs-muted" style={{ padding: '4rem 0' }}>
              Loading plans…
            </div>
          ) : (
            <PlanComparison
              currentPlan={currentPlan}
              period={period}
              onPeriodChange={setPeriod}
              onUpgrade={handleUpgrade}
              isUpgrading={createInvoiceMutation.isPending}
            />
          )}
      </div>
    </main>
  );
};
