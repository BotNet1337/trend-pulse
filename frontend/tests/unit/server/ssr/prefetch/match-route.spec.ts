/**
 * match-route unit tests — TrendPulse C1.
 *
 * Tests the generic matchRoute utility. Workspace/channel patterns removed
 * (not in TrendPulse C1 — route-map is empty pending C3 watchlists SSR).
 */
import { describe, expect, it } from 'vitest';
import { matchRoute } from '../../../../../server/ssr/prefetch/match-route';

describe('matchRoute', () => {
  it('returns null when no patterns are provided', () => {
    const result = matchRoute('/account/settings', []);
    expect(result).toBeNull();
  });

  it('returns null for unmatched pathname', () => {
    const result = matchRoute('/unknown-path', ['/account/settings']);
    expect(result).toBeNull();
  });

  it('matches exact static path', () => {
    const result = matchRoute('/account/settings', ['/account/settings']);
    expect(result).toEqual({ pattern: '/account/settings', params: {} });
  });

  it('matches a pattern with a dynamic segment', () => {
    const result = matchRoute('/items/abc-123', ['/items/$id']);
    expect(result).toEqual({ pattern: '/items/$id', params: { id: 'abc-123' } });
  });

  it('returns the most specific pattern (first match wins)', () => {
    const patterns = ['/items/$id/detail', '/items/$id'];
    const result = matchRoute('/items/abc-123/detail', patterns);
    expect(result).toEqual({ pattern: '/items/$id/detail', params: { id: 'abc-123' } });
  });

  it('falls through to less specific pattern', () => {
    const patterns = ['/items/$id/detail', '/items/$id'];
    const result = matchRoute('/items/abc-123', patterns);
    expect(result).toEqual({ pattern: '/items/$id', params: { id: 'abc-123' } });
  });

  it('decodes URL-encoded path params', () => {
    const result = matchRoute('/items/hello%20world', ['/items/$id']);
    expect(result).toEqual({ pattern: '/items/$id', params: { id: 'hello world' } });
  });

  it('returns null when segment count differs', () => {
    const result = matchRoute('/items/abc/extra', ['/items/$id']);
    expect(result).toBeNull();
  });
});
