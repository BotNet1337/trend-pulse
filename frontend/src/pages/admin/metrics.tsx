/**
 * AdminMetricsPage — /admin/metrics (TASK-063, superuser only).
 *
 * Money dashboard over GET /ops/business-metrics (TASK-051): MRR, active
 * subscriptions by plan, average check (30d), 30-day activation funnel and
 * retention (repeat_payment_rate).
 *
 * Access UX: a regular authenticated user sees the SAME markup as a real 404
 * (NotFoundPage) — no existence leak. The request is not even sent for
 * non-superusers (`enabled` guard), and a racy 403 (rights revoked while the
 * cached flag is stale) also collapses into the not-found state. The actual
 * protection is `current_superuser` on the server route — this page is UX only.
 */

import React from 'react';
import { useCurrentUser } from '@/entities/viewer/model';
import {
  formatPercent,
  formatRetention,
  formatUsd,
  planEntries,
  shouldShowAdminNotFound,
  totalActiveSubscriptions,
  useBusinessMetrics,
} from '@/features/admin-metrics';
import type { FunnelDayRow } from '@/features/admin-metrics';
import { useLogout } from '@/features/auth';
import { Button } from '@/shared/components/button';
import { BRAND_NAME } from '@/shared/config';
import { NotFoundPage } from '@/pages/error';

const FUNNEL_COLUMNS: Array<{ key: keyof FunnelDayRow; label: string }> = [
  { key: 'day', label: 'Day' },
  { key: 'registrations', label: 'Registrations' },
  { key: 'packs_attached', label: 'Packs attached' },
  { key: 'first_alerts_delivered', label: 'First alerts' },
  { key: 'first_feedback', label: 'First feedback' },
  { key: 'new_paid', label: 'New paid' },
  { key: 'churned', label: 'Churned' },
  { key: 'active_paid', label: 'Active paid' },
];

interface MetricCardProps {
  title: string;
  children: React.ReactNode;
}

const MetricCard: React.FC<MetricCardProps> = ({ title, children }) => (
  <section className="border border-border rounded-lg p-4 flex flex-col gap-2">
    <h2 className="text-xs uppercase tracking-wide text-muted-foreground">{title}</h2>
    {children}
  </section>
);

export const AdminMetricsPage: React.FC = () => {
  const logoutMutation = useLogout();
  const { data: user, isLoading: isUserLoading } = useCurrentUser();

  const isSuperuser = user?.is_superuser === true;
  const {
    data: metrics,
    isLoading: isMetricsLoading,
    error,
  } = useBusinessMetrics(isSuperuser);

  const errorStatus = (error as { response?: { status?: number } } | null)?.response
    ?.status;

  // Regular user (or racy 403): render the exact same markup as a real 404 —
  // no mention of admin or permissions (no existence leak).
  if (shouldShowAdminNotFound(user, errorStatus)) {
    return <NotFoundPage />;
  }

  const isLoading = isUserLoading || (isSuperuser && isMetricsLoading);

  return (
    <div className="auth-light min-h-dvh flex flex-col bg-background text-foreground">
      <header className="border-b border-border px-6 py-3 flex items-center gap-3">
        <span className="font-semibold text-sm flex-1">{BRAND_NAME}</span>
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

      <main className="flex-1 container max-w-4xl mx-auto px-4 py-8 flex flex-col gap-6">
        {isLoading && (
          <div aria-busy="true" aria-label="Loading metrics" className="flex justify-center py-16">
            <span className="text-muted-foreground text-sm">Loading…</span>
          </div>
        )}

        {!isLoading && error && errorStatus !== 403 && (
          <p role="alert" className="text-sm text-destructive">
            Failed to load metrics. Please refresh.
          </p>
        )}

        {!isLoading && metrics && (
          <>
            <h1 className="text-xl font-bold">Business metrics</h1>

            {/* Money cards */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <MetricCard title="MRR">
                <p className="text-2xl font-bold">{formatUsd(metrics.mrr)}</p>
              </MetricCard>

              <MetricCard title="Active subscriptions">
                <p className="text-2xl font-bold">
                  {totalActiveSubscriptions(metrics.active_subscriptions_by_plan)} active
                </p>
                <ul className="text-sm text-muted-foreground flex flex-col gap-1">
                  {planEntries(metrics.active_subscriptions_by_plan).map(([plan, count]) => (
                    <li key={plan} className="flex justify-between gap-2">
                      <span className="capitalize">{plan}</span>
                      <span>{count}</span>
                    </li>
                  ))}
                </ul>
              </MetricCard>

              <MetricCard title="Avg check (30d)">
                <p className="text-2xl font-bold">{formatUsd(metrics.avg_check_30d)}</p>
              </MetricCard>
            </div>

            {/* Retention + conversion */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <MetricCard title="Repeat payment rate">
                <p className="text-2xl font-bold">
                  {formatRetention(metrics.repeat_payment_rate)}
                </p>
              </MetricCard>

              <MetricCard title="Conversion Free → Paid (30d)">
                <p className="text-2xl font-bold">
                  {formatPercent(metrics.funnel_last_30d.conversion_free_to_paid)}
                </p>
              </MetricCard>
            </div>

            {/* Activation funnel — daily rows */}
            <section className="flex flex-col gap-2">
              <h2 className="text-sm font-semibold">Activation funnel — last 30 days</h2>
              {metrics.funnel_last_30d.daily.length === 0 ? (
                <p className="text-sm text-muted-foreground border border-border rounded-lg p-4">
                  No funnel data yet.
                </p>
              ) : (
                <div className="overflow-x-auto border border-border rounded-lg">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-left">
                        {FUNNEL_COLUMNS.map((col) => (
                          <th
                            key={col.key}
                            className="px-3 py-2 font-medium text-muted-foreground whitespace-nowrap"
                          >
                            {col.label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {metrics.funnel_last_30d.daily.map((row) => (
                        <tr key={row.day} className="border-b border-border last:border-b-0">
                          {FUNNEL_COLUMNS.map((col) => (
                            <td key={col.key} className="px-3 py-2 whitespace-nowrap">
                              {row[col.key]}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
};
