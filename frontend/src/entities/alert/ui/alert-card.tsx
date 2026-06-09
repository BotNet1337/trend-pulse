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
  delivered:
    'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300',
  failed: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
  pending:
    'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300',
};

const STATUS_LABELS: Record<string, string> = {
  delivered: 'Delivered',
  failed: 'Failed',
  pending: 'Pending',
};

export const AlertCard: React.FC<AlertCardProps> = ({ alert, onClick }) => {
  const { id, score, topic, first_seen, channels_count, delivery_status } = alert;

  const statusStyle =
    STATUS_STYLES[delivery_status] ??
    'bg-muted text-muted-foreground';
  const statusLabel =
    STATUS_LABELS[delivery_status] ?? delivery_status;

  return (
    <article
      className="border border-border rounded-lg p-4 flex flex-col gap-3 bg-card text-card-foreground cursor-pointer hover:bg-accent/5 transition-colors"
      aria-label={`Alert: ${topic} — score ${Math.round(score)}`}
      onClick={() => onClick?.(id)}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === 'Enter' || e.key === ' ') onClick(id); } : undefined}
    >
      <div className="flex items-start justify-between gap-3">
        {/* Score badge */}
        <span
          className="inline-flex items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-bold px-2.5 py-1 min-w-[2.5rem]"
          aria-label={`Score: ${Math.round(score)}`}
          title={`Score: ${score.toFixed(1)}`}
        >
          {Math.round(score)}
        </span>

        {/* Delivery status badge — accessible via aria-label */}
        <span
          className={`inline-flex items-center rounded-full text-xs font-medium px-2 py-0.5 ${statusStyle}`}
          aria-label={`Delivery status: ${statusLabel}`}
        >
          {/* Text rendered as-is — JSX auto-escapes, XSS safe */}
          {statusLabel}
        </span>
      </div>

      {/* Topic — text node, JSX auto-escapes */}
      <p className="text-sm font-semibold text-foreground line-clamp-2" title={topic}>
        {topic}
      </p>

      <div className="flex items-center justify-between text-xs text-muted-foreground gap-2">
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
