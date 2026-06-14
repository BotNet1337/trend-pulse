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
  <section className="fs-card metric-card">
    <h2 className="metric-card__title">{title}</h2>
    {children}
  </section>
);

export const AdminMetricsPage: React.FC = () => {
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
    <main className="fs-main">
      <div className="fs-container">
        {isLoading && (
          <div aria-busy="true" aria-label="Loading metrics" className="fs-center" style={{ padding: '4rem 0' }}>
            <span className="fs-muted">Loading…</span>
          </div>
        )}

        {!isLoading && error && errorStatus !== 403 && (
          <p role="alert" className="fs-error">
            Failed to load metrics. Please refresh.
          </p>
        )}

        {!isLoading && metrics && (
          <>
            <div className="fs-page-head">
              <h1 className="fs-page-head__title">
                Business metrics
                <span className="fs-badge fs-badge--info admin-badge">Admin</span>
              </h1>
            </div>

            {/* Money cards */}
            <div className="metric-grid">
              <MetricCard title="MRR">
                <p className="metric-card__value">{formatUsd(metrics.mrr)}</p>
              </MetricCard>

              <MetricCard title="Active subscriptions">
                <p className="metric-card__value">
                  {totalActiveSubscriptions(metrics.active_subscriptions_by_plan)} active
                </p>
                <ul className="metric-card__list">
                  {planEntries(metrics.active_subscriptions_by_plan).map(([plan, count]) => (
                    <li key={plan}>
                      <span className="plan-name">{plan}</span>
                      <span>{count}</span>
                    </li>
                  ))}
                </ul>
              </MetricCard>

              <MetricCard title="Avg check (30d)">
                <p className="metric-card__value">{formatUsd(metrics.avg_check_30d)}</p>
              </MetricCard>
            </div>

            {/* Retention + conversion */}
            <div className="metric-grid metric-grid--2">
              <MetricCard title="Repeat payment rate">
                <p className="metric-card__value">
                  {formatRetention(metrics.repeat_payment_rate)}
                </p>
              </MetricCard>

              <MetricCard title="Conversion Free → Paid (30d)">
                <p className="metric-card__value">
                  {formatPercent(metrics.funnel_last_30d.conversion_free_to_paid)}
                </p>
              </MetricCard>
            </div>

            {/* Activation funnel — daily rows */}
            <section className="funnel-section" aria-labelledby="funnel-heading">
              <h2 id="funnel-heading">Activation funnel — last 30 days</h2>
              {metrics.funnel_last_30d.daily.length === 0 ? (
                <p className="fs-muted fs-card fs-card--pad-sm">
                  No funnel data yet.
                </p>
              ) : (
                <div className="fs-table-wrap">
                  <table className="fs-table fs-table--hover funnel-table">
                    <thead>
                      <tr>
                        {FUNNEL_COLUMNS.map((col) => (
                          <th key={col.key} scope="col">
                            {col.label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {metrics.funnel_last_30d.daily.map((row) => (
                        <tr key={row.day}>
                          {FUNNEL_COLUMNS.map((col) => (
                            <td key={col.key}>{row[col.key]}</td>
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
      </div>
    </main>
  );
};
