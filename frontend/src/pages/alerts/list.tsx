/**
 * AlertsListPage — /alerts
 *
 * Shows the user's alerts feed (GET /alerts, paginated "Load more").
 * States:
 *   - history_unavailable (Free plan) → plan-upgrade upsell + empty state
 *   - no alerts (Pro/Team, empty) → friendly empty state with CTA to watchlists
 *   - loading → spinner
 *   - error → error message
 *   - list → AlertCard rows + "Load more" button
 */

import React from 'react';
import { useNavigate } from '@tanstack/react-router';
import { useAlerts } from '@/features/alerts';
import { AlertCard } from '@/entities/alert';
import { Button } from '@/shared/components/button';
import { EmptyState } from '@/shared/components/empty-state';
import { UpsellBanner } from '@/shared/components/upsell-banner';
import { useCurrentUser } from '@/entities/viewer/model';
import { paths } from '@/app/router/path';

export const AlertsListPage: React.FC = () => {
  const navigate = useNavigate();
  const { data: viewer } = useCurrentUser();
  const {
    data,
    isLoading,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useAlerts();

  // Flatten pages into a single items array
  const allItems = data?.pages.flatMap((page) => page.items) ?? [];

  // History unavailable comes from the first page
  const historyUnavailable = data?.pages[0]?.history_unavailable ?? false;

  const handleAlertClick = (id: number) => {
    void navigate({ to: '/alerts/$alertId', params: { alertId: String(id) } });
  };

  return (
    <main className="fs-main">
      <div className="fs-container">
        <div className="fs-page-head">
          <h1 className="fs-page-head__title">Alerts</h1>
        </div>

        {/* History unavailable (Free plan) — upsell banner */}
        {historyUnavailable && (
          <div style={{ marginBottom: '1.5rem' }}>
            <UpsellBanner
              message="Alert history is available on Pro and Team plans. Upgrade to see your full alert history."
              currentPlan={viewer?.plan}
            />
          </div>
        )}

        {isLoading && (
          <div
            aria-busy="true"
            aria-label="Loading alerts"
            className="fs-center"
            style={{ padding: '4rem 0' }}
          >
            <span className="fs-muted">Loading…</span>
          </div>
        )}

        {!isLoading && error && (
          <p role="alert" className="fs-error">
            Failed to load alerts. Please refresh.
          </p>
        )}

        {/* History unavailable empty state */}
        {!isLoading && !error && historyUnavailable && (
          <EmptyState
            title="No alert history on your plan"
            description="Alert history is available on Pro and Team plans. Upgrade to see your full alert history and track viral trends over time."
          />
        )}

        {/* Normal empty state (no alerts, history is available) */}
        {!isLoading && !error && !historyUnavailable && allItems.length === 0 && (
          <EmptyState
            title="No alerts yet"
            description="Alerts appear here when scored content crosses your watchlist thresholds. Create a watchlist to start tracking."
            ctaLabel="Create watchlist"
            onCta={() => void navigate({ to: paths.watchlists.create })}
          />
        )}

        {/* Alerts list */}
        {!isLoading && !error && allItems.length > 0 && (
          <>
            <ul className="fs-list" aria-label="Your alerts">
              {allItems.map((alert) => (
                <li key={alert.id}>
                  <AlertCard alert={alert} onClick={handleAlertClick} />
                </li>
              ))}
            </ul>

            {hasNextPage && (
              <div className="fs-load-more">
                <Button
                  type="button"
                  variant="outline"
                  disabled={isFetchingNextPage}
                  onClick={() => void fetchNextPage()}
                >
                  {isFetchingNextPage ? 'Loading…' : 'Load more'}
                </Button>
              </div>
            )}
          </>
        )}
      </div>
    </main>
  );
};
