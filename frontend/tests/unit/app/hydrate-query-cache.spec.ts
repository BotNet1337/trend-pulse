import { describe, expect, it, vi } from 'vitest';
import type { QueryClient } from '@tanstack/react-query';

import { hydrateQueryCache } from '../../../src/app/hydrate-query-cache';
import type { SerializedQuery } from '../../../src/shared/ssr/initial-state.types';

const buildClient = () => {
  const setQueryData = vi.fn();
  const client = { setQueryData } as unknown as QueryClient;
  return { client, setQueryData };
};

describe('hydrateQueryCache', () => {
  it('does nothing when queries is undefined', () => {
    const { client, setQueryData } = buildClient();
    hydrateQueryCache(client, undefined);
    expect(setQueryData).not.toHaveBeenCalled();
  });

  it('does nothing when queries is empty', () => {
    const { client, setQueryData } = buildClient();
    hydrateQueryCache(client, []);
    expect(setQueryData).not.toHaveBeenCalled();
  });

  it('seeds every entry verbatim', () => {
    const { client, setQueryData } = buildClient();
    const queries: SerializedQuery[] = [
      { key: ['', 'workspaces', 0, 100, false, false], data: { data: [{ id: 'w1' }] } },
      { key: ['', 'workspaces', 'ws-1'], data: { id: 'ws-1' } },
      {
        key: ['', 'workspaces', 'ws-1', 'channels', 0, 100],
        data: { data: [], meta: {} },
      },
    ];

    hydrateQueryCache(client, queries);

    expect(setQueryData).toHaveBeenCalledTimes(3);
    expect(setQueryData).toHaveBeenNthCalledWith(1, queries[0].key, queries[0].data);
    expect(setQueryData).toHaveBeenNthCalledWith(2, queries[1].key, queries[1].data);
    expect(setQueryData).toHaveBeenNthCalledWith(3, queries[2].key, queries[2].data);
  });
});
