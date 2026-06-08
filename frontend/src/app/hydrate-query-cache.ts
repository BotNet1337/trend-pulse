import type { QueryClient } from '@tanstack/react-query';

import type { SerializedQuery } from '../shared/ssr/initial-state.types';

/**
 * Seed a TanStack Query cache from server-prefetched entries.
 *
 * Generic and entity-agnostic: each `{ key, data }` pair is fed to
 * `queryClient.setQueryData` verbatim. The `key` MUST match the runtime
 * query key produced by the corresponding client hook — otherwise the seed
 * is invisible and the hook refetches on mount.
 *
 * Hydration is best-effort: a missing or empty `queries` array means we
 * render exactly like a non-SSR session and let hooks fill the cache.
 */
export function hydrateQueryCache(
  queryClient: QueryClient,
  queries: readonly SerializedQuery[] | undefined,
): void {
  if (!queries || queries.length === 0) return;

  for (const { key, data } of queries) {
    queryClient.setQueryData(key, data);
  }
}
