/**
 * Unit tests: trending feature — query key construction and API module shapes.
 *
 * Tests pure helpers only (no React mount, no jsdom).
 * Pattern: mirrors tests/unit/packs/packs-api.spec.ts.
 */

import { describe, it, expect } from 'vitest';
import { trendingQueryKey, TRENDING_QUERY_KEY_PREFIX } from '../../../src/features/trending/queries';

describe('trendingQueryKey', () => {
  it('returns a tuple starting with the prefix', () => {
    const key = trendingQueryKey('crypto-ru');
    expect(key[0]).toBe(TRENDING_QUERY_KEY_PREFIX);
  });

  it('includes the pack slug', () => {
    const key = trendingQueryKey('crypto-ru');
    expect(key[1]).toBe('crypto-ru');
  });

  it('includes limit when provided', () => {
    const key = trendingQueryKey('tech-en', 5);
    expect(key[2]).toBe(5);
  });

  it('includes undefined when limit not provided', () => {
    const key = trendingQueryKey('tech-en');
    expect(key[2]).toBeUndefined();
  });

  it('two different packs produce different keys', () => {
    const k1 = trendingQueryKey('crypto-ru');
    const k2 = trendingQueryKey('tech-en');
    expect(k1).not.toEqual(k2);
  });

  it('same pack same limit produce equal keys', () => {
    const k1 = trendingQueryKey('crypto-ru', 10);
    const k2 = trendingQueryKey('crypto-ru', 10);
    expect(k1).toEqual(k2);
  });
});

describe('TRENDING_QUERY_KEY_PREFIX', () => {
  it('is the string "trending"', () => {
    expect(TRENDING_QUERY_KEY_PREFIX).toBe('trending');
  });
});
