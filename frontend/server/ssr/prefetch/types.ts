import type { AxiosInstance } from 'axios';
import type { SerializedQuery } from '../../../src/shared/ssr/initial-state.types';

export interface FetcherCtx {
  /** Per-request axios instance with the inbound `Cookie` header stamped on. */
  api: AxiosInstance;
  /** Shared abort signal — fired on global timeout. */
  signal: AbortSignal;
  /** Path params extracted by the route matcher (workspaceId, postId, …). */
  params: Record<string, string | undefined>;
  /** Original URL search params — used to derive list filters (status, range, …). */
  search: URLSearchParams;
}

/**
 * Atomic resource fetcher. Returns one cache entry on success, or `null`
 * when there is nothing to prefetch (e.g. required path param missing).
 *
 * Errors and timeouts are NOT swallowed here — the runner catches them via
 * `Promise.allSettled` so a single failure can't poison the rest.
 */
export type Fetcher = (ctx: FetcherCtx) => Promise<SerializedQuery | null>;
