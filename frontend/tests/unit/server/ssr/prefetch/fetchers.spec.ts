import { describe, expect, it, vi } from 'vitest';
import type { AxiosInstance } from 'axios';

import {
  fetchChannelsList,
  fetchPostById,
  fetchPostsList,
  fetchWorkspaceById,
  fetchWorkspacePublications,
  fetchWorkspacesList,
} from '../../../../../server/ssr/prefetch/fetchers';
import type { FetcherCtx } from '../../../../../server/ssr/prefetch/types';

interface MockApi {
  get: ReturnType<typeof vi.fn>;
}

const buildCtx = (overrides: Partial<FetcherCtx> = {}): FetcherCtx & { api: MockApi } => {
  const mockApi: MockApi = {
    get: vi.fn(async () => ({ data: { data: [], meta: { pagination: {} } } })),
  };
  return {
    api: mockApi as unknown as AxiosInstance,
    signal: new AbortController().signal,
    params: {},
    search: new URLSearchParams(),
    ...overrides,
  } as FetcherCtx & { api: MockApi };
};

describe('fetchers', () => {
  describe('fetchWorkspacesList', () => {
    it('hits /workspaces and produces a key matching the workspaces list builder', async () => {
      const ctx = buildCtx();
      const result = await fetchWorkspacesList(ctx);

      expect(ctx.api.get).toHaveBeenCalledTimes(1);
      const [url] = ctx.api.get.mock.calls[0];
      expect(url).toBe('/workspaces');

      expect(result).not.toBeNull();
      expect(result?.key).toBeInstanceOf(Array);
      expect(result?.key.length).toBeGreaterThan(0);
    });
  });

  describe('fetchWorkspaceById', () => {
    it('returns null without workspaceId param', async () => {
      const ctx = buildCtx();
      const result = await fetchWorkspaceById(ctx);
      expect(result).toBeNull();
      expect(ctx.api.get).not.toHaveBeenCalled();
    });

    it('hits /workspaces/:id when workspaceId is present', async () => {
      const ctx = buildCtx({ params: { workspaceId: 'ws-1' } });
      ctx.api.get.mockResolvedValueOnce({ data: { id: 'ws-1' } });

      const result = await fetchWorkspaceById(ctx);

      expect(ctx.api.get).toHaveBeenCalledWith('/workspaces/ws-1');
      expect(result?.data).toEqual({ id: 'ws-1' });
    });
  });

  describe('fetchChannelsList', () => {
    it('returns null without workspaceId', async () => {
      const ctx = buildCtx();
      expect(await fetchChannelsList(ctx)).toBeNull();
    });

    it('queries /workspaces/:id/channels', async () => {
      const ctx = buildCtx({ params: { workspaceId: 'ws-1' } });
      await fetchChannelsList(ctx);
      expect(ctx.api.get).toHaveBeenCalledWith('/workspaces/ws-1/channels', expect.any(Object));
    });
  });

  describe('fetchPostsList', () => {
    it('returns null without workspaceId', async () => {
      expect(await fetchPostsList(buildCtx())).toBeNull();
    });

    it('forwards search/status/range filters as query params', async () => {
      const ctx = buildCtx({
        params: { workspaceId: 'ws-1' },
        search: new URLSearchParams(
          'search=launch&status=draft,published&rangeFrom=2026-01-01&channelId=ch-1',
        ),
      });
      ctx.api.get.mockResolvedValueOnce({
        data: { data: [], meta: { pagination: {} } },
      });

      await fetchPostsList(ctx);

      const call = ctx.api.get.mock.calls[0];
      expect(call[0]).toBe('/workspaces/ws-1/posts');
      expect(call[1].params).toMatchObject({
        search: 'launch',
        status: 'draft,published',
        rangeFrom: '2026-01-01',
        channelId: 'ch-1',
      });
    });
  });

  describe('fetchPostById', () => {
    it('returns null without postId', async () => {
      const ctx = buildCtx({ params: { workspaceId: 'ws-1' } });
      expect(await fetchPostById(ctx)).toBeNull();
    });

    it('hits the post detail endpoint', async () => {
      const ctx = buildCtx({ params: { workspaceId: 'ws-1', postId: 'post-1' } });
      ctx.api.get.mockResolvedValueOnce({
        data: { id: 'post-1', publications: [] },
      });

      const result = await fetchPostById(ctx);

      expect(ctx.api.get).toHaveBeenCalledWith('/workspaces/ws-1/posts/post-1');
      expect(result?.data).toMatchObject({ id: 'post-1' });
    });
  });

  describe('fetchWorkspacePublications', () => {
    it('returns null without workspaceId', async () => {
      expect(await fetchWorkspacePublications(buildCtx())).toBeNull();
    });

    it('queries the new workspace-wide publications endpoint', async () => {
      const ctx = buildCtx({ params: { workspaceId: 'ws-1' } });
      await fetchWorkspacePublications(ctx);
      expect(ctx.api.get).toHaveBeenCalledWith(
        '/workspaces/ws-1/publications',
        expect.any(Object),
      );
    });
  });
});
