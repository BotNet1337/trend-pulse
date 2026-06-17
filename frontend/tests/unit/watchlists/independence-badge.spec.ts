/**
 * Unit tests: source-independence badge helpers (TASK-126).
 *
 * `formatIndependenceBadge` is the pure helper that gates the "N independent
 * sources" chip: it returns a label only when `effective_sources` is finite and
 * at/above `MIN_INDEPENDENCE_DISPLAY` (single-source ~1 is hidden as no "trust"
 * noise), else `null`. The tooltip is an HONEST organic-spread framing — never a
 * coordination / anti-fraud verdict (RQ3).
 */

import { describe, it, expect } from 'vitest';
import {
  MIN_INDEPENDENCE_DISPLAY,
  formatIndependenceBadge,
  formatIndependenceTooltip,
  rowSignal,
} from '../../../src/features/watchlists/signal-desk';
import type { WatchlistRead } from '../../../src/entities/watchlist';

describe('MIN_INDEPENDENCE_DISPLAY', () => {
  it('is a finite threshold above 1 (single-source not shown as trust)', () => {
    expect(Number.isFinite(MIN_INDEPENDENCE_DISPLAY)).toBe(true);
    expect(MIN_INDEPENDENCE_DISPLAY).toBeGreaterThan(1);
  });
});

describe('formatIndependenceBadge', () => {
  it('returns null for null / undefined', () => {
    expect(formatIndependenceBadge(null)).toBeNull();
    expect(formatIndependenceBadge(undefined)).toBeNull();
  });

  it('returns null for non-finite values', () => {
    expect(formatIndependenceBadge(Number.NaN)).toBeNull();
    expect(formatIndependenceBadge(Number.POSITIVE_INFINITY)).toBeNull();
  });

  it('returns null when below the display threshold (single-source ~1)', () => {
    expect(formatIndependenceBadge(1.0)).toBeNull();
    expect(formatIndependenceBadge(MIN_INDEPENDENCE_DISPLAY - 0.01)).toBeNull();
  });

  it('returns a rounded "N independent sources" label at/above the threshold', () => {
    expect(formatIndependenceBadge(MIN_INDEPENDENCE_DISPLAY)).toBe('2 independent sources');
    expect(formatIndependenceBadge(3.0)).toBe('3 independent sources');
    expect(formatIndependenceBadge(4.6)).toBe('5 independent sources');
  });

  it('uses singular wording when N rounds to 1 is impossible above threshold', () => {
    // threshold > 1 guarantees the displayed N is >= 2, so the label is plural.
    const label = formatIndependenceBadge(MIN_INDEPENDENCE_DISPLAY);
    expect(label).toContain('sources');
  });
});

describe('formatIndependenceTooltip', () => {
  it('frames independence as an organic-spread signal, not a coordination verdict', () => {
    const tip = formatIndependenceTooltip(3.0);
    expect(tip.toLowerCase()).toContain('organic');
    expect(tip.toLowerCase()).toContain('not a coordination');
    expect(tip).toContain('3');
  });
});

describe('rowSignal fallback', () => {
  it('carries effective_sources: null in the all-empty fallback', () => {
    const watchlist = { signal: null } as unknown as WatchlistRead;
    expect(rowSignal(watchlist).effective_sources).toBeNull();
  });
});
