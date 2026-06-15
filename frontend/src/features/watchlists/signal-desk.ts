/**
 * Signal Desk — pure presentational helpers for the watchlists table.
 *
 * VISUAL ONLY: these helpers drive the client-side UI state (search, status
 * segment, density, column sort) and shape the live-signal columns of the
 * redesigned `/watchlists` screen. They never touch data fetching, mutations or
 * routing.
 *
 * Backend reality (WatchlistRead, ADR-001): a watchlist = exactly one channel
 * plus a topic, an alert_config (score_threshold / min_channels / lang) and a
 * live `signal` (TASK-096): `live_velocity`, `live_score`, `sparkline_24h`,
 * `last_alert_at`. Every signal field is graceful (null / empty when there is no
 * data) — these helpers preserve that and never fabricate values.
 */

import type { WatchlistRead, WatchlistSignal } from '@/entities/watchlist';

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

// ── Live signal helpers (TASK-096) ─────────────────────────────────────────────

/** Velocity badge tier — maps the CSS classes `.vel-badge.{hot,warm,calm}`. */
export type VelocityTier = 'hot' | 'warm' | 'calm';

/**
 * Velocity tiers over the scorer's normalized velocity (∈ [0, 1]). Thresholds:
 * hot ≥ 0.5, warm ≥ 0.2, else calm. `null`/non-finite velocity → `calm` (the
 * neutral, no-data tier). Chosen in TASK-096 ## Discussion.
 */
export const VELOCITY_HOT_THRESHOLD = 0.5;
export const VELOCITY_WARM_THRESHOLD = 0.2;

export function velocityTier(velocity: number | null | undefined): VelocityTier {
  if (velocity == null || !Number.isFinite(velocity)) return 'calm';
  if (velocity >= VELOCITY_HOT_THRESHOLD) return 'hot';
  if (velocity >= VELOCITY_WARM_THRESHOLD) return 'warm';
  return 'calm';
}

/**
 * Human label for the velocity badge: a "×baseline"-style multiplier. The scorer
 * velocity is a normalized [0, 1] burst term, surfaced as `×{n.n}` (one decimal).
 * Returns `null` when there is no velocity → the row shows its no-data placeholder.
 */
export function formatVelocityBadge(velocity: number | null | undefined): string | null {
  if (velocity == null || !Number.isFinite(velocity)) return null;
  return `×${velocity.toFixed(1)} baseline`;
}

/** A sparkline column has a real series only when it carries ≥1 finite point. */
export function hasSparkline(series: readonly number[] | null | undefined): boolean {
  return Array.isArray(series) && series.some((v) => Number.isFinite(v));
}

/**
 * Map an hourly `viral_score` series (0-100, oldest→newest) to SVG polyline
 * points inside `width`×`height`. Y is inverted (higher score → higher on
 * screen) and the series is normalized to its own max so a flat-but-present
 * series still draws a visible line. Empty/invalid series → `''` (caller renders
 * the placeholder). A single point draws a flat mid line across the width.
 */
export function sparklinePoints(
  series: readonly number[] | null | undefined,
  width: number,
  height: number,
): string {
  if (!hasSparkline(series) || width <= 0 || height <= 0) return '';
  const points = (series as number[]).filter((v) => Number.isFinite(v));
  const max = Math.max(...points, 0);
  const safeMax = max > 0 ? max : 1;
  if (points.length === 1) {
    const y = height - (points[0] / safeMax) * height;
    return `0,${y.toFixed(1)} ${width},${y.toFixed(1)}`;
  }
  const stepX = width / (points.length - 1);
  return points
    .map((value, index) => {
      const x = index * stepX;
      const y = height - (value / safeMax) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
}

/**
 * Short, locale-agnostic "last alert" label from an ISO timestamp. Returns
 * `null` when there is no alert (caller renders the `—` placeholder). Compact
 * relative form: `just now`, `Nm ago`, `Nh ago`, `Nd ago`, else a date.
 */
export function formatLastAlert(
  isoTimestamp: string | null | undefined,
  now: Date = new Date(),
): string | null {
  if (!isoTimestamp) return null;
  const then = new Date(isoTimestamp);
  if (Number.isNaN(then.getTime())) return null;
  const diffMs = now.getTime() - then.getTime();
  if (diffMs < 0) return 'just now';
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return then.toISOString().slice(0, 10);
}

/** Convenience accessor: the row's signal, or an all-empty signal fallback. */
export function rowSignal(watchlist: WatchlistRead): WatchlistSignal {
  return (
    watchlist.signal ?? {
      live_velocity: null,
      live_score: null,
      sparkline_24h: [],
      last_alert_at: null,
    }
  );
}
