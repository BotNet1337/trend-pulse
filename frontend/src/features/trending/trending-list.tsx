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
  <li className="flex items-start gap-3 p-3 rounded-lg border border-border bg-card">
    <span className="text-muted-foreground text-sm font-mono w-5 shrink-0">{rank}.</span>
    <div className="flex-1 min-w-0">
      <p className="font-semibold text-sm truncate">{item.topic}</p>
      <p className="text-xs text-muted-foreground mt-0.5">
        Virality: {formatScore(item.viral_score)} &middot;{' '}
        {formatDate(item.first_seen as unknown as string)}
      </p>
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
      <div aria-busy="true" aria-label="Loading trends" className="py-6 flex justify-center">
        <span className="text-sm text-muted-foreground">Loading…</span>
      </div>
    );
  }

  if (isError) {
    return (
      <p role="alert" className="text-sm text-destructive py-4">
        Failed to load trends. Please refresh the page.
      </p>
    );
  }

  if (warmingUp) {
    return (
      <div
        className="py-6 flex flex-col items-center gap-2 text-center"
        aria-label="Collecting data"
      >
        <span className="text-2xl">📡</span>
        <p className="text-sm font-medium">Collecting signals…</p>
        <p className="text-xs text-muted-foreground">
          The showcase has just started. Data will appear within a few minutes.
        </p>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-4">
        No activity detected for this pack in the last 24 hours.
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-2" aria-label="Viral topics over the last 24 hours">
      {items.map((item, idx) => (
        <TrendingItemRow key={`${item.topic}-${idx}`} item={item} rank={idx + 1} />
      ))}
    </ul>
  );
};
