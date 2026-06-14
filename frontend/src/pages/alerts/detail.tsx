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
import { useAlert, useSendFeedback } from '@/features/alerts';
import type { FeedbackVerdict } from '@/features/alerts';
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

// Feedback button copy (EN — all UI strings are English per TASK-064).
const FEEDBACK_UP_LABEL = 'Mark this alert as useful';
const FEEDBACK_DOWN_LABEL = 'Mark this alert as not useful';
const FEEDBACK_ERROR_MESSAGE = "Couldn't save your rating. Refresh the page and try again.";

interface AlertFeedbackButtonsProps {
  alertId: number;
  feedback: string | null | undefined;
  tokenUp: string | null | undefined;
  tokenDown: string | null | undefined;
}

/**
 * 👍/👎 feedback buttons for the alert detail page (TASK-064).
 *
 * Graceful degradation: rendered only when BOTH feedback tokens are present
 * (the backend omits them when minting is unavailable). Buttons are disabled
 * while a mutation is in flight; a re-tap of the active verdict still sends
 * (idempotent UPSERT). On failure an EN error message is announced via role="alert".
 */
const AlertFeedbackButtons: React.FC<AlertFeedbackButtonsProps> = ({
  alertId,
  feedback,
  tokenUp,
  tokenDown,
}) => {
  const mutation = useSendFeedback(alertId);

  // Graceful degradation: hide the buttons entirely when tokens are absent.
  if (!tokenUp || !tokenDown) return null;

  const rate = (token: string, verdict: FeedbackVerdict) => {
    mutation.mutate({ token, verdict });
  };

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <button
          type="button"
          aria-pressed={feedback === 'up'}
          aria-label={FEEDBACK_UP_LABEL}
          disabled={mutation.isPending}
          onClick={() => rate(tokenUp, 'up')}
          className={`inline-flex items-center justify-center rounded-full border min-h-11 min-w-11 text-lg transition-colors disabled:opacity-50 ${
            feedback === 'up'
              ? 'border-primary bg-primary/10 text-primary'
              : 'border-border text-muted-foreground hover:text-foreground'
          }`}
        >
          <span aria-hidden="true">👍</span>
        </button>
        <button
          type="button"
          aria-pressed={feedback === 'down'}
          aria-label={FEEDBACK_DOWN_LABEL}
          disabled={mutation.isPending}
          onClick={() => rate(tokenDown, 'down')}
          className={`inline-flex items-center justify-center rounded-full border min-h-11 min-w-11 text-lg transition-colors disabled:opacity-50 ${
            feedback === 'down'
              ? 'border-primary bg-primary/10 text-primary'
              : 'border-border text-muted-foreground hover:text-foreground'
          }`}
        >
          <span aria-hidden="true">👎</span>
        </button>
      </div>
      {mutation.isError && (
        <p role="alert" className="text-xs text-destructive">
          {FEEDBACK_ERROR_MESSAGE}
        </p>
      )}
    </div>
  );
};

export const AlertDetailPage: React.FC = () => {
  const { alertId } = useParams({ strict: false }) as { alertId?: string };
  const numericId = alertId ? parseInt(alertId, 10) : NaN;

  const { data: alert, isLoading, error } = useAlert(numericId);

  const is404 =
    Number.isNaN(numericId) ||
    (error as { response?: { status?: number } } | null)?.response?.status === 404;

  return (
    <main className="fs-main">
      <div className="mx-auto max-w-2xl px-4">
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
            <div className="flex items-start gap-4 flex-wrap">
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

              {/* 👍/👎 feedback (TASK-064) — hidden when tokens absent */}
              <AlertFeedbackButtons
                alertId={alert.id}
                feedback={alert.feedback}
                tokenUp={alert.feedback_token_up}
                tokenDown={alert.feedback_token_down}
              />
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
      </div>
    </main>
  );
};
