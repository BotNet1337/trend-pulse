/**
 * SSR prefetch fetchers spec — TrendPulse C1.
 *
 * C1 fetchers are all no-op stubs (returning null). Real fetchers land in C3
 * when watchlists SSR prefetch is implemented.
 */
import { describe, expect, it } from 'vitest';
import {
  fetchWorkspacesList,
  fetchWorkspaceById,
  fetchChannelsList,
  fetchPostsList,
  fetchPostById,
  fetchWorkspacePublications,
  fetchDashboard,
  fetchModerationQueue,
} from '../../../../../server/ssr/prefetch/fetchers';
import type { FetcherCtx } from '../../../../../server/ssr/prefetch/types';
import type { AxiosInstance } from 'axios';

const makeCtx = (): FetcherCtx => ({
  api: {} as AxiosInstance,
  signal: new AbortController().signal,
  params: {},
  search: new URLSearchParams(),
});

describe('C1 stub fetchers', () => {
  const stubs = [
    { name: 'fetchWorkspacesList', fn: fetchWorkspacesList },
    { name: 'fetchWorkspaceById', fn: fetchWorkspaceById },
    { name: 'fetchChannelsList', fn: fetchChannelsList },
    { name: 'fetchPostsList', fn: fetchPostsList },
    { name: 'fetchPostById', fn: fetchPostById },
    { name: 'fetchWorkspacePublications', fn: fetchWorkspacePublications },
    { name: 'fetchDashboard', fn: fetchDashboard },
    { name: 'fetchModerationQueue', fn: fetchModerationQueue },
  ];

  for (const { name, fn } of stubs) {
    it(`${name} returns null (C1 stub)`, async () => {
      const result = await fn(makeCtx());
      expect(result).toBeNull();
    });
  }
});
