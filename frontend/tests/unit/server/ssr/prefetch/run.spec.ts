import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { getMock, createServerApiClientMock } = vi.hoisted(() => {
  const getMock = vi.fn();
  const createServerApiClientMock = vi.fn(() => ({ get: getMock }));
  return { getMock, createServerApiClientMock };
});

vi.mock('../../../../../server/client', () => ({
  createServerApiClient: createServerApiClientMock,
  serverApiClient: { get: getMock },
}));

import { runPrefetch } from '../../../../../server/ssr/prefetch/run';

describe('runPrefetch', () => {
  beforeEach(() => {
    getMock.mockReset();
    createServerApiClientMock.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns [] when the path does not match any pattern', async () => {
    const queries = await runPrefetch({
      pathname: '/auth/sign-in',
      search: new URLSearchParams(),
      accessToken: 'x',
    });
    expect(queries).toEqual([]);
    expect(createServerApiClientMock).not.toHaveBeenCalled();
  });

  it('runs every fetcher for the matched composition and returns survivors', async () => {
    getMock.mockImplementation(async (url: string) => ({
      data:
        url === '/workspaces'
          ? { data: [], meta: { pagination: {} } }
          : url === '/workspaces/ws-1'
            ? { id: 'ws-1' }
            : { data: [], meta: { pagination: {} } },
    }));

    const queries = await runPrefetch({
      pathname: '/workspaces/ws-1/posts',
      search: new URLSearchParams(),
      accessToken: 'x',
    });

    expect(queries.length).toBe(4);
    expect(createServerApiClientMock).toHaveBeenCalledOnce();
    expect(createServerApiClientMock.mock.calls[0][0].accessToken).toBe('x');
  });

  it('drops a single failing fetcher but keeps the rest', async () => {
    getMock.mockImplementation(async (url: string) => {
      if (url === '/workspaces/ws-1/channels') {
        throw new Error('upstream blew up');
      }
      return { data: { data: [], meta: { pagination: {} } } };
    });

    const queries = await runPrefetch({
      pathname: '/workspaces/ws-1',
      search: new URLSearchParams(),
      accessToken: 'x',
    });

    expect(queries.length).toBe(2);
  });

  it('wipes everything when any fetcher returns 401', async () => {
    const error = Object.assign(new Error('Unauthorized'), {
      isAxiosError: true,
      response: { status: 401, data: 'unauthorized' },
      toJSON: () => ({}),
    });

    getMock.mockImplementation(async (url: string) => {
      if (url === '/workspaces/ws-1/channels') throw error;
      return { data: { data: [], meta: { pagination: {} } } };
    });

    const queries = await runPrefetch({
      pathname: '/workspaces/ws-1',
      search: new URLSearchParams(),
      accessToken: 'stale',
    });

    expect(queries).toEqual([]);
  });
});
