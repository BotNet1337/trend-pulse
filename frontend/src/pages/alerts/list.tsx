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
import { Link, useNavigate } from '@tanstack/react-router';
import { useAlerts } from '@/features/alerts';
import { AlertCard } from '@/entities/alert';
import { Button } from '@/shared/components/button';
import { EmptyState } from '@/shared/components/empty-state';
import { UpsellBanner } from '@/shared/components/upsell-banner';
import { BRAND_NAME } from '@/shared/config';
import { useLogout } from '@/features/auth';
import { useCurrentUser } from '@/entities/viewer/model';
import { paths } from '@/app/router/path';

export const AlertsListPage: React.FC = () => {
  const navigate = useNavigate();
  const logoutMutation = useLogout();
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
    <div className="auth-light min-h-dvh flex flex-col bg-background text-foreground">
      <header className="border-b border-border px-6 py-3 flex items-center gap-3">
        <span className="font-semibold text-sm flex-1">{BRAND_NAME}</span>
        <nav className="flex items-center gap-3 text-sm">
          <Link
            to={paths.watchlists.list}
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            Watchlists
          </Link>
          <Link
            to={paths.account.settings}
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            Settings
          </Link>
        </nav>
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

      <main className="flex-1 container max-w-3xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">Alerts</h1>
        </div>

        {/* History unavailable (Free plan) — upsell banner */}
        {historyUnavailable && (
          <div className="mb-6">
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
            className="flex justify-center py-16"
          >
            <span className="text-muted-foreground text-sm">Loading…</span>
          </div>
        )}

        {!isLoading && error && (
          <p role="alert" className="text-sm text-destructive">
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
            <ul className="flex flex-col gap-4" aria-label="Your alerts">
              {allItems.map((alert) => (
                <li key={alert.id}>
                  <AlertCard alert={alert} onClick={handleAlertClick} />
                </li>
              ))}
            </ul>

            {hasNextPage && (
              <div className="flex justify-center mt-6">
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
      </main>
    </div>
  );
};
