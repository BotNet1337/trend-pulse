/**
 * BillingPage — /billing route (TASK-017, Epic C/C5).
 *
 * Shows plan comparison (Free/Pro/Team) and handles upgrade → crypto invoice.
 * INVARIANT: No Stripe. Only POST /billing/invoice (NOWPayments).
 * INVARIANT: plan data from GET /users/me (useCurrentUser), not hardcoded.
 */

import * as React from 'react';
import { useNavigate } from '@tanstack/react-router';

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
import { Button } from '@/shared/components/button';
import { BRAND_NAME } from '@/shared/config';
import { useLogout } from '@/features/auth';

export const BillingPage: React.FC = () => {
  const { data: currentUser, isLoading } = useCurrentUser();
  const logoutMutation = useLogout();
  const navigate = useNavigate();

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
    <div className="auth-light h-screen flex flex-col bg-background text-foreground overflow-hidden">
      <header className="border-b border-border px-8 py-3 flex items-center gap-3">
        <span className="font-semibold text-sm flex-1">{BRAND_NAME}</span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => void navigate({ to: '/account/invite' })}
          aria-label="Invite a friend"
        >
          Invite
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => void navigate({ to: '/account/settings' })}
          aria-label="Account settings"
        >
          Settings
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={logoutMutation.isPending}
          onClick={() => logoutMutation.mutate()}
          aria-label="Sign out"
        >
          {logoutMutation.isPending ? 'Signing out…' : 'Sign out'}
        </Button>
      </header>

      <main className="flex-1 min-w-0 bg-background overflow-y-auto">
        <div className="mx-auto flex w-full max-w-[960px] flex-col gap-8 px-8 py-8">
          <header className="flex flex-col gap-2">
            <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground font-medium">
              Billing
            </span>
            <h1 className="m-0 text-2xl font-bold tracking-[-0.01em]">
              Plans & billing
            </h1>
            {!isLoading && currentUser && (
              <p className="m-0 text-sm text-muted-foreground">
                Current plan:{' '}
                <span className="font-semibold text-foreground">
                  {currentPlanDisplay}
                </span>
              </p>
            )}
          </header>

          {/* Invoice display (shown after upgrade click) */}
          {pendingInvoice && (
            <InvoiceDisplay invoice={pendingInvoice} />
          )}

          {/* Invoice error */}
          {createInvoiceMutation.isError && (
            <div
              role="alert"
              className="rounded-xl border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive"
            >
              {createInvoiceMutation.error?.message ?? 'Failed to create invoice. Please try again.'}
            </div>
          )}

          {/* Plan comparison */}
          {isLoading ? (
            <div className="flex items-center justify-center py-16 text-muted-foreground text-sm">
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
    </div>
  );
};
