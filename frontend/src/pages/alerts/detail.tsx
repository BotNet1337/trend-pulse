/**
 * AlertDetailPage — /alerts/:alertId
 *
 * Shows full details for one alert: score, topic, first_seen, channels_count,
 * delivery_status. Foreign or nonexistent id → not-found state (404, no existence leak).
 *
 * XSS safety: topic and delivery_status rendered via JSX text — no dangerouslySetInnerHTML.
 */

import React from 'react';
import { Link, useParams } from '@tanstack/react-router';
import { useAlert } from '@/features/alerts';
import { Button } from '@/shared/components/button';
import { BRAND_NAME } from '@/shared/config';
import { useLogout } from '@/features/auth';
import { paths } from '@/app/router/path';

function formatFirstSeen(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: 'long',
      timeStyle: 'medium',
    });
  } catch {
    return iso;
  }
}

const STATUS_STYLES: Record<string, string> = {
  delivered: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300',
  failed: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
  pending: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300',
};

const STATUS_LABELS: Record<string, string> = {
  delivered: 'Delivered',
  failed: 'Failed',
  pending: 'Pending',
};

export const AlertDetailPage: React.FC = () => {
  const { alertId } = useParams({ from: '/alerts/$alertId' });
  const numericId = parseInt(alertId, 10);
  const logoutMutation = useLogout();

  const { data: alert, isLoading, error } = useAlert(numericId);

  const is404 =
    Number.isNaN(numericId) ||
    (error as { response?: { status?: number } } | null)?.response?.status === 404;

  return (
    <div className="auth-light min-h-dvh flex flex-col bg-background text-foreground">
      <header className="border-b border-border px-6 py-3 flex items-center gap-3">
        <span className="font-semibold text-sm flex-1">{BRAND_NAME}</span>
        <nav className="flex items-center gap-3 text-sm">
          <Link
            to={paths.alerts.list}
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            ← All alerts
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

      <main className="flex-1 container max-w-2xl mx-auto px-4 py-8">
        {isLoading && (
          <div aria-busy="true" aria-label="Loading alert" className="flex justify-center py-16">
            <span className="text-muted-foreground text-sm">Loading…</span>
          </div>
        )}

        {/* Not found state: foreign id, NaN, or 404 error */}
        {!isLoading && (is404 || (!alert && !error)) && (
          <div className="flex flex-col items-center gap-4 py-16 text-center">
            <h2 className="text-xl font-semibold">Alert not found</h2>
            <p className="text-muted-foreground text-sm max-w-sm">
              This alert doesn&apos;t exist or you don&apos;t have access to it.
            </p>
            <Link
              to={paths.alerts.list}
              className="text-primary underline underline-offset-2 text-sm"
            >
              Back to alerts
            </Link>
          </div>
        )}

        {!isLoading && !is404 && error && (
          <p role="alert" className="text-sm text-destructive">
            Failed to load alert. Please refresh.
          </p>
        )}

        {/* Alert detail */}
        {!isLoading && alert && (
          <article className="flex flex-col gap-6">
            <div className="flex items-start gap-4">
              {/* Score badge */}
              <span
                className="inline-flex items-center justify-center rounded-full bg-primary text-primary-foreground text-sm font-bold px-3 py-1.5 min-w-[3rem]"
                aria-label={`Score: ${Math.round(alert.score)}`}
              >
                {Math.round(alert.score)}
              </span>

              <div className="flex-1 min-w-0">
                {/* Topic — text node, JSX auto-escapes */}
                <h1 className="text-xl font-bold text-foreground" title={alert.topic}>
                  {alert.topic}
                </h1>
              </div>

              {/* Delivery status badge */}
              <span
                className={`inline-flex items-center rounded-full text-xs font-medium px-2.5 py-1 ${STATUS_STYLES[alert.delivery_status] ?? 'bg-muted text-muted-foreground'}`}
                aria-label={`Delivery status: ${STATUS_LABELS[alert.delivery_status] ?? alert.delivery_status}`}
              >
                {/* Text rendered as-is — JSX auto-escapes */}
                {STATUS_LABELS[alert.delivery_status] ?? alert.delivery_status}
              </span>
            </div>

            <dl className="grid grid-cols-2 gap-4 border border-border rounded-lg p-4 text-sm">
              <div>
                <dt className="text-muted-foreground text-xs uppercase tracking-wide mb-1">
                  First seen
                </dt>
                <dd>
                  <time dateTime={alert.first_seen}>
                    {formatFirstSeen(alert.first_seen)}
                  </time>
                </dd>
              </div>

              <div>
                <dt className="text-muted-foreground text-xs uppercase tracking-wide mb-1">
                  Channels
                </dt>
                <dd aria-label={`${alert.channels_count} channels`}>
                  {alert.channels_count}
                </dd>
              </div>

              <div>
                <dt className="text-muted-foreground text-xs uppercase tracking-wide mb-1">
                  Score
                </dt>
                <dd>{alert.score.toFixed(2)}</dd>
              </div>

              <div>
                <dt className="text-muted-foreground text-xs uppercase tracking-wide mb-1">
                  Alert ID
                </dt>
                <dd className="font-mono text-xs">{alert.id}</dd>
              </div>
            </dl>
          </article>
        )}
      </main>
    </div>
  );
};
