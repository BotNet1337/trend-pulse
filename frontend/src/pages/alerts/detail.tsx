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
  delivered: 'fs-badge--success',
  failed: 'fs-badge--danger',
  pending: 'fs-badge--warning',
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
      <div className="feedback">
        <button
          type="button"
          aria-pressed={feedback === 'up'}
          aria-label={FEEDBACK_UP_LABEL}
          disabled={mutation.isPending}
          onClick={() => rate(tokenUp, 'up')}
          className="fs-btn fs-btn--ghost"
        >
          <span aria-hidden="true">👍</span>
        </button>
        <button
          type="button"
          aria-pressed={feedback === 'down'}
          aria-label={FEEDBACK_DOWN_LABEL}
          disabled={mutation.isPending}
          onClick={() => rate(tokenDown, 'down')}
          className="fs-btn fs-btn--ghost"
        >
          <span aria-hidden="true">👎</span>
        </button>
      </div>
      {mutation.isError && (
        <p role="alert" className="fs-error">
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
      <div className="fs-container">
        {isLoading && (
          <div aria-busy="true" aria-label="Loading alert" className="fs-center" style={{ padding: '4rem 0' }}>
            <span className="fs-muted">Loading…</span>
          </div>
        )}

        {/* Not found state: foreign id, NaN, or 404 error */}
        {!isLoading && (is404 || (!alert && !error)) && (
          <div className="fs-empty">
            <h2 className="fs-empty__title">Alert not found</h2>
            <p className="fs-empty__text">
              This alert doesn&apos;t exist or you don&apos;t have access to it.
            </p>
            <Link to={paths.alerts.list} className="back-link">
              Back to alerts
            </Link>
          </div>
        )}

        {!isLoading && !is404 && error && (
          <p role="alert" className="fs-error">
            Failed to load alert. Please refresh.
          </p>
        )}

        {/* Alert detail */}
        {!isLoading && alert && (
          <>
            <Link to={paths.alerts.list} className="back-link">
              <span aria-hidden="true">←</span> All alerts
            </Link>

            <article className="alert-detail">
              <div className="alert-head">
                {/* Score badge */}
                <span className="fs-score" aria-label={`Score: ${Math.round(alert.score)}`}>
                  {Math.round(alert.score)}
                </span>

                {/* Topic — text node, JSX auto-escapes */}
                <h1 className="alert-head__title" title={alert.topic}>
                  {alert.topic}
                </h1>

                {/* Delivery status badge */}
                <span
                  className={`fs-badge ${STATUS_STYLES[alert.delivery_status] ?? 'fs-badge--neutral'}`}
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

              <div className="fs-card alert-meta-card">
                <dl className="fs-meta">
                  <div>
                    <dt>First seen</dt>
                    <dd>
                      <time dateTime={alert.first_seen}>
                        {formatFirstSeen(alert.first_seen)}
                      </time>
                    </dd>
                  </div>

                  <div>
                    <dt>Channels</dt>
                    <dd aria-label={`${alert.channels_count} channels`}>
                      {alert.channels_count}
                    </dd>
                  </div>

                  <div>
                    <dt>Score</dt>
                    <dd>{alert.score.toFixed(2)}</dd>
                  </div>

                  <div>
                    <dt>Alert ID</dt>
                    <dd className="fs-mono">{alert.id}</dd>
                  </div>
                </dl>
              </div>
            </article>
          </>
        )}
      </div>
    </main>
  );
};
