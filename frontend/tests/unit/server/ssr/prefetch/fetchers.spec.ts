/**
 * SSR prefetch fetchers spec — TrendPulse C1.
 *
 * C1 has no real prefetch: the only fetcher is a no-op placeholder returning
 * null. Real named fetchers (watchlists) land in C3 (task-015).
 */
import { describe, expect, it } from 'vitest';
import { fetchPlaceholder } from '../../../../../server/ssr/prefetch/fetchers';
import type { FetcherCtx } from '../../../../../server/ssr/prefetch/types';
import type { AxiosInstance } from 'axios';

const makeCtx = (): FetcherCtx => ({
  api: {} as AxiosInstance,
  signal: new AbortController().signal,
  params: {},
  search: new URLSearchParams(),
});

describe('C1 placeholder fetcher', () => {
  it('fetchPlaceholder returns null (nothing to hydrate)', async () => {
    const result = await fetchPlaceholder(makeCtx());
    expect(result).toBeNull();
  });

  it('fetchPlaceholder returns null regardless of params', async () => {
    const result = await fetchPlaceholder({ ...makeCtx(), params: { id: '1' } });
    expect(result).toBeNull();
  });
});
