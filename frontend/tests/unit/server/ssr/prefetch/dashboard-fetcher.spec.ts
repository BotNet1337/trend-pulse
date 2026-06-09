/**
 * Dashboard fetcher spec — TrendPulse C1.
 *
 * Dashboard analytics feature is not in TrendPulse C1 (ref project artifact).
 * fetchDashboard is a no-op stub; this spec just confirms it returns null.
 */
import { describe, expect, it } from 'vitest';
import { fetchDashboard } from '../../../../../server/ssr/prefetch/fetchers';
import type { FetcherCtx } from '../../../../../server/ssr/prefetch/types';
import type { AxiosInstance } from 'axios';

const makeCtx = (): FetcherCtx => ({
  api: {} as AxiosInstance,
  signal: new AbortController().signal,
  params: {},
  search: new URLSearchParams(),
});

describe('fetchDashboard', () => {
  it('returns null (C1 stub — analytics in C4+)', async () => {
    const result = await fetchDashboard(makeCtx());
    expect(result).toBeNull();
  });

  it('returns null without a workspaceId param', async () => {
    const result = await fetchDashboard({ ...makeCtx(), params: {} });
    expect(result).toBeNull();
  });
});
