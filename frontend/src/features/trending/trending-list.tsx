/**
 * TrendingList — renders viral clusters from GET /trending.
 *
 * States:
 *  - loading   → spinner placeholder
 *  - error     → user-friendly error message
 *  - warming_up → "Collecting signals…" placeholder (showcase not yet warmed)
 *  - empty     → honest empty state (no 24h activity for this pack)
 *  - items     → ranked list of trending topics with viral_score + first_seen
 */

import React from 'react';
import type { TrendingItem } from './api';

interface TrendingListProps {
  items: TrendingItem[];
  isLoading: boolean;
  isError: boolean;
  warmingUp: boolean;
}

function formatScore(score: number): string {
  return score.toFixed(1);
}

function formatDate(iso: string): string {
  try {
    // Browser locale (same pattern as alert-card) — EN-only product, no ru-RU pin.
    return new Date(iso).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

const TrendingItemRow: React.FC<{ item: TrendingItem; rank: number }> = ({ item, rank }) => (
  <li className="fs-list__row ob-trend-row">
    <span className="ob-rank" aria-hidden="true">{rank}.</span>
    <div className="fs-list__main" style={{ flex: 1 }}>
      <span className="fs-list__title fs-truncate" title={item.topic}>{item.topic}</span>
      <span className="fs-list__sub">
        Virality: {formatScore(item.viral_score)} &middot;{' '}
        {formatDate(item.first_seen as unknown as string)}
      </span>
    </div>
  </li>
);

export const TrendingList: React.FC<TrendingListProps> = ({
  items,
  isLoading,
  isError,
  warmingUp,
}) => {
  if (isLoading) {
    return (
      <div aria-busy="true" aria-label="Loading trends" className="fs-center" style={{ padding: '1.5rem 0' }}>
        <span className="fs-muted">Loading…</span>
      </div>
    );
  }

  if (isError) {
    return (
      <p role="alert" className="fs-error" style={{ padding: '1rem 0' }}>
        Failed to load trends. Please refresh the page.
      </p>
    );
  }

  if (warmingUp) {
    return (
      <div className="fs-card fs-card--pad-sm fs-center" aria-label="Collecting data">
        <span style={{ fontSize: '1.5rem' }}>📡</span>
        <p className="fs-mt-1" style={{ fontWeight: 500, marginBottom: '0.25rem' }}>Collecting signals…</p>
        <p className="fs-hint">
          The showcase has just started. Data will appear within a few minutes.
        </p>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="fs-card fs-card--pad-sm">
        <p className="fs-muted fs-mt-0" style={{ margin: 0 }}>
          No activity detected for this pack in the last 24 hours.
        </p>
      </div>
    );
  }

  return (
    <div className="fs-card fs-card--pad-sm">
      <ul className="fs-list fs-list--flush" aria-label="Viral topics over the last 24 hours">
        {items.map((item, idx) => (
          <TrendingItemRow key={`${item.topic}-${idx}`} item={item} rank={idx + 1} />
        ))}
      </ul>
    </div>
  );
};
