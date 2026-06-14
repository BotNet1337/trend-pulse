/**
 * AlertCard — displays one alert in the feed.
 *
 * Shows: score badge, topic, first_seen (UTC→locale), channels_count,
 * delivery_status (visually distinct: delivered/failed/pending).
 *
 * XSS safety: topic and delivery_status are rendered via JSX text nodes —
 * no dangerouslySetInnerHTML. Both are accessible to screen readers.
 */

import React from 'react';
import type { AlertRead } from '../model';

interface AlertCardProps {
  alert: AlertRead;
  onClick?: (id: number) => void;
}

function formatFirstSeen(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
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

export const AlertCard: React.FC<AlertCardProps> = ({ alert, onClick }) => {
  const { id, score, topic, first_seen, channels_count, delivery_status } = alert;

  const statusStyle = STATUS_STYLES[delivery_status] ?? 'fs-badge--neutral';
  const statusLabel =
    STATUS_LABELS[delivery_status] ?? delivery_status;

  return (
    <article
      className="fs-card fs-card--interactive alert-card"
      aria-label={`Alert: ${topic} — score ${Math.round(score)}`}
      onClick={() => onClick?.(id)}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === 'Enter' || e.key === ' ') onClick(id); } : undefined}
    >
      <div className="fs-card__head">
        {/* Score badge */}
        <span
          className="fs-score"
          aria-label={`Score: ${Math.round(score)}`}
          title={`Score: ${score.toFixed(1)}`}
        >
          {Math.round(score)}
        </span>

        {/* Delivery status badge — accessible via aria-label */}
        <span
          className={`fs-badge ${statusStyle}`}
          aria-label={`Delivery status: ${statusLabel}`}
        >
          {/* Text rendered as-is — JSX auto-escapes, XSS safe */}
          {statusLabel}
        </span>
      </div>

      {/* Topic — text node, JSX auto-escapes */}
      <p className="alert-card__headline fs-truncate" title={topic}>
        {topic}
      </p>

      <div className="alert-card__meta">
        {/* first_seen: UTC → locale string */}
        <time dateTime={first_seen} title={first_seen}>
          {formatFirstSeen(first_seen)}
        </time>

        {/* channels_count */}
        <span aria-label={`${channels_count} channels`}>
          {channels_count} {channels_count === 1 ? 'channel' : 'channels'}
        </span>
      </div>
    </article>
  );
};
