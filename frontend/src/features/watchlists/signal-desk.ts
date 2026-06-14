/**
 * Signal Desk — pure presentational helpers for the watchlists table.
 *
 * VISUAL ONLY: these helpers drive the client-side UI state (search, status
 * segment, density, column sort) of the redesigned `/watchlists` screen. They
 * never touch data fetching, mutations or routing.
 *
 * Backend reality (WatchlistRead, ADR-001): a watchlist = exactly one channel
 * plus a topic and an alert_config (score_threshold / min_channels / lang).
 * There is no live-velocity, sparkline, last-alert or pause/active field, so
 * those columns degrade to neutral placeholders — we never fabricate values.
 */

import type { WatchlistRead } from '@/entities/watchlist';

/** Client-side status segment. Only states the backend can back truthfully. */
export type DeskStatus = 'all' | 'active';

/** Row density toggle (mockup: Comfortable / Compact). */
export type DeskDensity = 'comfortable' | 'compact';

/** Sortable columns. `signal` has no backend series → name is the stable key. */
export type DeskSortKey = 'name' | 'sources' | 'threshold';

export type DeskSortDir = 'asc' | 'desc';

export interface DeskSort {
  key: DeskSortKey;
  dir: DeskSortDir;
}

/** Score threshold runs 0–100; clamp to a CSS bar width percentage. */
export function thresholdBarPercent(scoreThreshold: number): number {
  if (!Number.isFinite(scoreThreshold)) return 0;
  return Math.max(0, Math.min(100, Math.round(scoreThreshold)));
}

/**
 * Number of source channels behind a watchlist. ADR-001: one channel each, so
 * this is always 1 today — kept as a function so a future multi-source model
 * has a single place to grow.
 */
export function sourcesCount(_watchlist: WatchlistRead): number {
  return 1;
}

/**
 * Case-insensitive substring match over the fields a user would search by:
 * channel handle and topic. Empty/whitespace query matches everything.
 */
export function matchesQuery(watchlist: WatchlistRead, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q === '') return true;
  const handle = watchlist.channel.handle.toLowerCase();
  const topic = watchlist.topic.toLowerCase();
  return handle.includes(q) || topic.includes(q);
}

/**
 * Status segment filter. Every watchlist is "active" today (no pause field),
 * so `all` and `active` are equivalent — but keeping the predicate explicit
 * means the segment stays correct if a real status field is added later.
 */
export function matchesStatus(_watchlist: WatchlistRead, status: DeskStatus): boolean {
  if (status === 'all') return true;
  // No pause concept in the backend model → every row counts as active.
  return true;
}

function compareByKey(a: WatchlistRead, b: WatchlistRead, key: DeskSortKey): number {
  switch (key) {
    case 'name':
      return a.channel.handle.localeCompare(b.channel.handle, undefined, {
        sensitivity: 'base',
      });
    case 'sources':
      return sourcesCount(a) - sourcesCount(b);
    case 'threshold':
      return a.alert_config.score_threshold - b.alert_config.score_threshold;
    default:
      return 0;
  }
}

/**
 * Pure, non-mutating filter + sort pipeline for the table body. Returns a new
 * array; the input is never mutated (immutability invariant).
 */
export function selectVisibleWatchlists(
  watchlists: readonly WatchlistRead[],
  options: { query: string; status: DeskStatus; sort: DeskSort },
): WatchlistRead[] {
  const { query, status, sort } = options;
  const filtered = watchlists.filter(
    (wl) => matchesQuery(wl, query) && matchesStatus(wl, status),
  );
  const sorted = [...filtered].sort((a, b) => {
    const cmp = compareByKey(a, b, sort.key);
    // Stable tiebreak on id so equal keys keep a deterministic order.
    const tiebreak = cmp !== 0 ? cmp : a.id - b.id;
    return sort.dir === 'asc' ? tiebreak : -tiebreak;
  });
  return sorted;
}

/** aria-sort attribute value for a column header given the active sort. */
export function ariaSortFor(column: DeskSortKey, sort: DeskSort): 'ascending' | 'descending' | 'none' {
  if (sort.key !== column) return 'none';
  return sort.dir === 'asc' ? 'ascending' : 'descending';
}

/** Toggle helper: clicking the active column flips direction, else sort desc. */
export function nextSort(current: DeskSort, column: DeskSortKey): DeskSort {
  if (current.key === column) {
    return { key: column, dir: current.dir === 'asc' ? 'desc' : 'asc' };
  }
  return { key: column, dir: 'desc' };
}
