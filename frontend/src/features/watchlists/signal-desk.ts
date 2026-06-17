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

/** Sortable columns: only the ones backed by real data (name + threshold).
 * `sources` is not sortable — every watchlist is one channel (ADR-001), so it
 * carries no ordering signal. */
export type DeskSortKey = 'name' | 'threshold';

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

function compareByKey(a: WatchlistRead, b: WatchlistRead, key: DeskSortKey): number {
  switch (key) {
    case 'name':
      return a.channel.handle.localeCompare(b.channel.handle, undefined, {
        sensitivity: 'base',
      });
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
  options: { query: string; sort: DeskSort },
): WatchlistRead[] {
  const { query, sort } = options;
  const filtered = watchlists.filter((wl) => matchesQuery(wl, query));
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

// ── viral_score badge (TASK-121) ───────────────────────────────────────────────

/**
 * viral_score tiers over the scorer's 0-100 `live_score`, reusing the same CSS
 * classes `.vel-badge.{hot,warm,calm}` as the velocity badge (one visual
 * language, no new CSS). Tier is colour only — the numeric truth is the value
 * rendered in the badge. `null`/non-finite score → `calm` (neutral, no-data).
 * Fixed named thresholds keep the diff minimal and the tier logic per-row
 * threshold-independent (see TASK-121 ## Discussion).
 */
export const SCORE_HOT_THRESHOLD = 40;
export const SCORE_WARM_THRESHOLD = 20;

export function scoreTier(score: number | null | undefined): VelocityTier {
  if (score == null || !Number.isFinite(score)) return 'calm';
  if (score >= SCORE_HOT_THRESHOLD) return 'hot';
  if (score >= SCORE_WARM_THRESHOLD) return 'warm';
  return 'calm';
}

/**
 * Human label for the primary live-signal badge: the viral_score as a rounded
 * integer 0-100 (tabular-nums, e.g. `47`). Returns `null` when there is no
 * score → the row shows its no-signal placeholder (INV2: never fabricate `0`
 * out of `null`; a real `0` still renders as `0`).
 */
export function formatScoreBadge(score: number | null | undefined): string | null {
  if (score == null || !Number.isFinite(score)) return null;
  // Clamp to the advertised 0-100 range (matches thresholdBarPercent) so a
  // future out-of-range scorer value never renders a badge that contradicts
  // the `/100` tooltip semantics.
  const bounded = Math.max(0, Math.min(100, score));
  return `${Math.round(bounded)}`;
}

/**
 * Tooltip for the primary score badge. Demotes velocity to secondary info
 * (TASK-121) while keeping it visible: `Live signal {score}/100 · velocity
 * ×{v.v} baseline`. The velocity clause is omitted when there is no velocity.
 * When there is no score at all, returns the no-signal label.
 */
export function formatSignalTooltip(
  score: number | null | undefined,
  velocity: number | null | undefined,
): string {
  const scoreLabel = formatScoreBadge(score);
  if (scoreLabel === null) return 'No live signal yet';
  const velocityLabel = formatVelocityBadge(velocity);
  const base = `Live signal ${scoreLabel}/100`;
  return velocityLabel === null ? base : `${base} · velocity ${velocityLabel}`;
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

// ── Source-independence badge (TASK-126) ───────────────────────────────────────

/**
 * Minimum `effective_sources` (effective number of independent sources) to surface
 * the independence chip. effective_sources collapses to ~1 for single-source
 * amplification (77% of clusters are single-channel), which is NOT a "trust" signal,
 * so the chip is shown only at/above this threshold — named, never a magic literal.
 */
export const MIN_INDEPENDENCE_DISPLAY = 2.0;

/**
 * Label for the independence chip: `N independent sources` where N is the rounded
 * `effective_sources`. Returns `null` (chip hidden) when the value is null /
 * non-finite or below `MIN_INDEPENDENCE_DISPLAY` (single-source ~1 is hidden, not
 * rendered as "1 independent source" noise). Honest framing: this is an organic-spread
 * signal, NOT a coordination verdict (RQ3).
 */
export function formatIndependenceBadge(
  effectiveSources: number | null | undefined,
): string | null {
  if (effectiveSources == null || !Number.isFinite(effectiveSources)) return null;
  if (effectiveSources < MIN_INDEPENDENCE_DISPLAY) return null;
  const n = Math.round(effectiveSources);
  const noun = n === 1 ? 'source' : 'sources';
  return `${n} independent ${noun}`;
}

/**
 * Honest tooltip for the independence chip: frames it as an organic-spread signal,
 * explicitly NOT a coordination / anti-fraud verdict (RQ3, AC6).
 */
export function formatIndependenceTooltip(effectiveSources: number): string {
  const n = Math.round(effectiveSources);
  return `${n} effective independent sources (organic spread signal, not a coordination verdict)`;
}

/** Convenience accessor: the row's signal, or an all-empty signal fallback. */
export function rowSignal(watchlist: WatchlistRead): WatchlistSignal {
  return (
    watchlist.signal ?? {
      live_velocity: null,
      live_score: null,
      sparkline_24h: [],
      last_alert_at: null,
      effective_sources: null,
    }
  );
}
