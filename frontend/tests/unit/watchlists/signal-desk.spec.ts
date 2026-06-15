/**
 * Unit tests: Signal Desk pure helpers (filter / sort / threshold bar).
 * These drive the redesigned /watchlists table's client-side UI state.
 */

import { describe, it, expect } from 'vitest';
import {
  thresholdBarPercent,
  sourcesCount,
  matchesQuery,
  matchesStatus,
  selectVisibleWatchlists,
  ariaSortFor,
  nextSort,
  velocityTier,
  formatVelocityBadge,
  hasSparkline,
  sparklinePoints,
  formatLastAlert,
  rowSignal,
  type DeskSort,
} from '../../../src/features/watchlists/signal-desk';
import type { WatchlistRead, WatchlistSignal } from '../../../src/entities/watchlist';

function makeWatchlist(overrides: {
  id: number;
  handle: string;
  topic: string;
  threshold: number;
  signal?: WatchlistSignal;
}): WatchlistRead {
  return {
    id: overrides.id,
    user_id: 1,
    topic: overrides.topic,
    channel: { handle: overrides.handle, kind: 'telegram' },
    alert_config: {
      score_threshold: overrides.threshold,
      min_channels: 2,
      notification_lang: 'en',
    },
    ...(overrides.signal ? { signal: overrides.signal } : {}),
  };
}

const sample: WatchlistRead[] = [
  makeWatchlist({ id: 1, handle: '@whale_alert_io', topic: 'bitcoin etf flows', threshold: 70 }),
  makeWatchlist({ id: 2, handle: '@ai_pulse_daily', topic: 'open-source LLM releases', threshold: 65 }),
  makeWatchlist({ id: 3, handle: '@defi_radar', topic: 'stablecoin depegs', threshold: 80 }),
];

describe('thresholdBarPercent', () => {
  it('clamps into 0..100', () => {
    expect(thresholdBarPercent(70)).toBe(70);
    expect(thresholdBarPercent(-5)).toBe(0);
    expect(thresholdBarPercent(150)).toBe(100);
  });

  it('rounds fractional thresholds', () => {
    expect(thresholdBarPercent(72.6)).toBe(73);
  });

  it('handles non-finite input as 0', () => {
    expect(thresholdBarPercent(Number.NaN)).toBe(0);
    expect(thresholdBarPercent(Number.POSITIVE_INFINITY)).toBe(0);
  });
});

describe('sourcesCount', () => {
  it('is 1 per watchlist (ADR-001 single channel)', () => {
    expect(sourcesCount(sample[0])).toBe(1);
  });
});

describe('matchesQuery', () => {
  it('matches everything for empty/whitespace query', () => {
    expect(matchesQuery(sample[0], '')).toBe(true);
    expect(matchesQuery(sample[0], '   ')).toBe(true);
  });

  it('matches on handle, case-insensitively', () => {
    expect(matchesQuery(sample[0], 'WHALE')).toBe(true);
    expect(matchesQuery(sample[0], 'ai_pulse')).toBe(false);
  });

  it('matches on topic', () => {
    expect(matchesQuery(sample[1], 'llm')).toBe(true);
    expect(matchesQuery(sample[1], 'depeg')).toBe(false);
  });
});

describe('matchesStatus', () => {
  it('all and active both match (no pause field in backend)', () => {
    expect(matchesStatus(sample[0], 'all')).toBe(true);
    expect(matchesStatus(sample[0], 'active')).toBe(true);
  });
});

describe('selectVisibleWatchlists', () => {
  it('does not mutate the input array', () => {
    const input = [...sample];
    const before = input.map((w) => w.id);
    selectVisibleWatchlists(input, {
      query: '',
      status: 'all',
      sort: { key: 'threshold', dir: 'asc' },
    });
    expect(input.map((w) => w.id)).toEqual(before);
  });

  it('filters by query then sorts by threshold ascending', () => {
    const result = selectVisibleWatchlists(sample, {
      query: '',
      status: 'all',
      sort: { key: 'threshold', dir: 'asc' },
    });
    expect(result.map((w) => w.alert_config.score_threshold)).toEqual([65, 70, 80]);
  });

  it('sorts by threshold descending', () => {
    const result = selectVisibleWatchlists(sample, {
      query: '',
      status: 'all',
      sort: { key: 'threshold', dir: 'desc' },
    });
    expect(result.map((w) => w.alert_config.score_threshold)).toEqual([80, 70, 65]);
  });

  it('sorts by name ascending', () => {
    const result = selectVisibleWatchlists(sample, {
      query: '',
      status: 'all',
      sort: { key: 'name', dir: 'asc' },
    });
    expect(result.map((w) => w.channel.handle)).toEqual([
      '@ai_pulse_daily',
      '@defi_radar',
      '@whale_alert_io',
    ]);
  });

  it('narrows to a single match on query', () => {
    const result = selectVisibleWatchlists(sample, {
      query: 'whale',
      status: 'all',
      sort: { key: 'name', dir: 'asc' },
    });
    expect(result).toHaveLength(1);
    expect(result[0].channel.handle).toBe('@whale_alert_io');
  });

  it('uses id as a stable tiebreak for equal sort keys', () => {
    const tied = [
      makeWatchlist({ id: 9, handle: '@b', topic: 't', threshold: 50 }),
      makeWatchlist({ id: 4, handle: '@a', topic: 't', threshold: 50 }),
    ];
    const result = selectVisibleWatchlists(tied, {
      query: '',
      status: 'all',
      sort: { key: 'threshold', dir: 'asc' },
    });
    expect(result.map((w) => w.id)).toEqual([4, 9]);
  });
});

describe('ariaSortFor', () => {
  const sort: DeskSort = { key: 'threshold', dir: 'desc' };
  it('returns descending/ascending for the active column', () => {
    expect(ariaSortFor('threshold', sort)).toBe('descending');
    expect(ariaSortFor('threshold', { key: 'threshold', dir: 'asc' })).toBe('ascending');
  });
  it('returns none for inactive columns', () => {
    expect(ariaSortFor('name', sort)).toBe('none');
  });
});

describe('nextSort', () => {
  it('flips direction when clicking the active column', () => {
    expect(nextSort({ key: 'name', dir: 'desc' }, 'name')).toEqual({ key: 'name', dir: 'asc' });
    expect(nextSort({ key: 'name', dir: 'asc' }, 'name')).toEqual({ key: 'name', dir: 'desc' });
  });
  it('defaults to descending when switching columns', () => {
    expect(nextSort({ key: 'name', dir: 'asc' }, 'threshold')).toEqual({
      key: 'threshold',
      dir: 'desc',
    });
  });
});

// ── Live signal helpers (TASK-096) ─────────────────────────────────────────────

describe('velocityTier', () => {
  it('maps the burst value into hot/warm/calm tiers', () => {
    expect(velocityTier(0.8)).toBe('hot');
    expect(velocityTier(0.5)).toBe('hot');
    expect(velocityTier(0.49)).toBe('warm');
    expect(velocityTier(0.2)).toBe('warm');
    expect(velocityTier(0.19)).toBe('calm');
    expect(velocityTier(0)).toBe('calm');
  });

  it('treats null/undefined/non-finite as the neutral calm tier', () => {
    expect(velocityTier(null)).toBe('calm');
    expect(velocityTier(undefined)).toBe('calm');
    expect(velocityTier(Number.NaN)).toBe('calm');
  });
});

describe('formatVelocityBadge', () => {
  it('renders a ×baseline multiplier with one decimal', () => {
    expect(formatVelocityBadge(0.65)).toBe('×0.7 baseline');
    expect(formatVelocityBadge(0)).toBe('×0.0 baseline');
  });

  it('returns null when there is no velocity (graceful placeholder)', () => {
    expect(formatVelocityBadge(null)).toBeNull();
    expect(formatVelocityBadge(undefined)).toBeNull();
    expect(formatVelocityBadge(Number.NaN)).toBeNull();
  });
});

describe('hasSparkline', () => {
  it('is true only for a series with at least one finite point', () => {
    expect(hasSparkline([1, 2, 3])).toBe(true);
    expect(hasSparkline([0])).toBe(true);
    expect(hasSparkline([])).toBe(false);
    expect(hasSparkline(null)).toBe(false);
    expect(hasSparkline(undefined)).toBe(false);
  });
});

describe('sparklinePoints', () => {
  it('returns empty string for empty/invalid series or sizes', () => {
    expect(sparklinePoints([], 76, 26)).toBe('');
    expect(sparklinePoints(null, 76, 26)).toBe('');
    expect(sparklinePoints([1, 2], 0, 26)).toBe('');
  });

  it('draws a flat mid-height line for a single point', () => {
    // single point at value==max → y at top (0); but at half-max → mid.
    expect(sparklinePoints([50], 64, 14)).toBe('0,0.0 64,0.0');
  });

  it('maps a series to inverted, normalized polyline points', () => {
    // max=100 normalizes; y is inverted (higher score → smaller y).
    const points = sparklinePoints([0, 50, 100], 64, 14);
    expect(points).toBe('0.0,14.0 32.0,7.0 64.0,0.0');
  });
});

describe('formatLastAlert', () => {
  const now = new Date('2026-06-15T12:00:00.000Z');

  it('returns null when there is no alert', () => {
    expect(formatLastAlert(null, now)).toBeNull();
    expect(formatLastAlert(undefined, now)).toBeNull();
    expect(formatLastAlert('not-a-date', now)).toBeNull();
  });

  it('formats compact relative times', () => {
    expect(formatLastAlert('2026-06-15T11:59:40.000Z', now)).toBe('just now');
    expect(formatLastAlert('2026-06-15T11:30:00.000Z', now)).toBe('30m ago');
    expect(formatLastAlert('2026-06-15T09:00:00.000Z', now)).toBe('3h ago');
    expect(formatLastAlert('2026-06-13T12:00:00.000Z', now)).toBe('2d ago');
  });

  it('falls back to a date for old alerts', () => {
    expect(formatLastAlert('2026-06-01T12:00:00.000Z', now)).toBe('2026-06-01');
  });
});

describe('rowSignal', () => {
  it('returns the row signal when present', () => {
    const signal: WatchlistSignal = {
      live_velocity: 0.4,
      live_score: 55,
      sparkline_24h: [10, 20],
      last_alert_at: '2026-06-15T11:00:00.000Z',
    };
    const wl = makeWatchlist({ id: 1, handle: '@a', topic: 't', threshold: 60, signal });
    expect(rowSignal(wl)).toEqual(signal);
  });

  it('falls back to an all-empty signal when absent', () => {
    const wl = makeWatchlist({ id: 2, handle: '@b', topic: 't', threshold: 60 });
    expect(rowSignal(wl)).toEqual({
      live_velocity: null,
      live_score: null,
      sparkline_24h: [],
      last_alert_at: null,
    });
  });
});
