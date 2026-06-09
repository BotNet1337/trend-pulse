/**
 * runPrefetch spec — TrendPulse C1.
 *
 * In C1 the route-map is empty (no SSR prefetch routes), so runPrefetch
 * always returns []. The full SSR hydration tests land in C3 with watchlists.
 */
import { describe, expect, it } from 'vitest';

import { runPrefetch } from '../../../../../server/ssr/prefetch/run';

describe('runPrefetch', () => {
  it('returns [] when the path does not match any pattern (route-map empty in C1)', async () => {
    const queries = await runPrefetch({
      pathname: '/account/settings',
      search: new URLSearchParams(),
      accessToken: 'test-token',
    });
    expect(queries).toEqual([]);
  });

  it('returns [] for auth paths (public, no SSR hydration)', async () => {
    const queries = await runPrefetch({
      pathname: '/auth/sign-in',
      search: new URLSearchParams(),
      accessToken: undefined,
    });
    expect(queries).toEqual([]);
  });

  it('returns [] for root path (redirects to protected content client-side)', async () => {
    const queries = await runPrefetch({
      pathname: '/',
      search: new URLSearchParams(),
      accessToken: 'test-token',
    });
    expect(queries).toEqual([]);
  });

  it('returns [] for unknown paths', async () => {
    const queries = await runPrefetch({
      pathname: '/this-does-not-exist',
      search: new URLSearchParams(),
      accessToken: undefined,
    });
    expect(queries).toEqual([]);
  });
});
