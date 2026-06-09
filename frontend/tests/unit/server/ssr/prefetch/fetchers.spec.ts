/**
 * SSR prefetch fetchers spec — TrendPulse TASK-029 (SSR enablement).
 *
 * Tests that fetchCurrentUser and fetchWatchlists return SerializedQuery
 * objects with the correct cache keys matching client hooks:
 *   - CURRENT_USER_QUERY_KEY = ['viewer', 'me']
 *   - WATCHLISTS_QUERY_KEY   = ['watchlists', 'list']
 */
import { describe, expect, it, vi } from 'vitest';
import { fetchCurrentUser, fetchWatchlists } from '../../../../../server/ssr/prefetch/fetchers';
import type { FetcherCtx } from '../../../../../server/ssr/prefetch/types';
import type { AxiosInstance } from 'axios';

const makeCtx = (apiOverride?: Partial<AxiosInstance>): FetcherCtx => ({
  api: (apiOverride ?? {}) as AxiosInstance,
  signal: new AbortController().signal,
  params: {},
  search: new URLSearchParams(),
});

describe('fetchCurrentUser', () => {
  it('returns SerializedQuery with key ["viewer", "me"]', async () => {
    const mockUser = { id: 'user-1', email: 'test@example.com', is_active: true, is_verified: false, is_superuser: false, plan: 'free' };
    const mockApi = {
      get: vi.fn().mockResolvedValue({ data: mockUser }),
    } as unknown as AxiosInstance;

    const result = await fetchCurrentUser(makeCtx(mockApi));

    expect(result).not.toBeNull();
    expect(result?.key).toEqual(['viewer', 'me']);
    expect(result?.data).toEqual(mockUser);
    expect(mockApi.get).toHaveBeenCalledWith('/users/me');
  });

  it('propagates errors (401 surfaces to runner)', async () => {
    const axiosError = Object.assign(new Error('Unauthorized'), {
      isAxiosError: true,
      response: { status: 401 },
    });
    const mockApi = {
      get: vi.fn().mockRejectedValue(axiosError),
    } as unknown as AxiosInstance;

    await expect(fetchCurrentUser(makeCtx(mockApi))).rejects.toThrow();
  });
});

describe('fetchWatchlists', () => {
  it('returns SerializedQuery with key ["watchlists", "list"]', async () => {
    const mockWatchlists = [{ id: 1, name: 'My list' }];
    const mockApi = {
      get: vi.fn().mockResolvedValue({ data: mockWatchlists }),
    } as unknown as AxiosInstance;

    const result = await fetchWatchlists(makeCtx(mockApi));

    expect(result).not.toBeNull();
    expect(result?.key).toEqual(['watchlists', 'list']);
    expect(result?.data).toEqual(mockWatchlists);
    expect(mockApi.get).toHaveBeenCalledWith('/watchlists');
  });

  it('propagates errors (401 surfaces to runner)', async () => {
    const axiosError = Object.assign(new Error('Unauthorized'), {
      isAxiosError: true,
      response: { status: 401 },
    });
    const mockApi = {
      get: vi.fn().mockRejectedValue(axiosError),
    } as unknown as AxiosInstance;

    await expect(fetchWatchlists(makeCtx(mockApi))).rejects.toThrow();
  });
});
