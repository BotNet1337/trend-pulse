import type { FastifyBaseLogger } from 'fastify';
import { isAxiosError } from 'axios';

import { createServerApiClient } from '../../client';
import type { SerializedQuery } from '../../../src/shared/ssr/initial-state.types';
import { matchRoute } from './match-route';
import {
  PARAM_ALIASES,
  PREFETCH_ROUTES,
  PREFETCH_ROUTE_PATTERNS,
} from './route-map';

export interface RunPrefetchArgs {
  pathname: string;
  search: URLSearchParams;
  /**
   * `access_token` from the inbound `request.cookies`, hoisted into an
   * `Authorization: Bearer …` header on the upstream axios client. The API
   * only honours Bearer tokens, so omitting this means every fetcher will
   * 401 and the whole hydration array is wiped to `[]`.
   */
  accessToken: string | undefined;
  /**
   * Global timeout shared across every fetcher in the composition. The first
   * fetcher to take longer than this will be aborted; the rest are aborted
   * cooperatively via the same `AbortSignal`.
   */
  timeoutMs?: number;
  logger?: FastifyBaseLogger;
}

const DEFAULT_TIMEOUT_MS = 800;

const isUnauthorized = (error: unknown): boolean => {
  if (isAxiosError(error)) {
    return error.response?.status === 401;
  }
  return false;
};

/**
 * Resolve the prefetch composition for the given request, run every fetcher
 * in parallel under a shared timeout, and return the surviving cache
 * entries.
 *
 * Failure policy:
 * - Any single fetcher rejecting (timeout, network, 5xx) → it is dropped
 *   from the result, the rest survive. Hydration is best-effort.
 * - ANY fetcher returning 401 → the result is wiped to `[]`. The cookie is
 *   stale and we don't want to render pre-authenticated content; the client
 *   will see an empty cache, refetch, and AuthGate redirects to login.
 * - No matched route → `[]`.
 */
export async function runPrefetch(args: RunPrefetchArgs): Promise<SerializedQuery[]> {
  const matched = matchRoute(args.pathname, PREFETCH_ROUTE_PATTERNS);
  if (!matched) return [];

  const fetchers = PREFETCH_ROUTES[matched.pattern] ?? [];
  if (fetchers.length === 0) return [];

  const params: Record<string, string | undefined> = {};
  for (const [name, value] of Object.entries(matched.params)) {
    const aliased = PARAM_ALIASES[name] ?? name;
    params[aliased] = value;
  }

  const timeoutMs = args.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const api = createServerApiClient({
      accessToken: args.accessToken,
      signal: controller.signal,
    });

    const results = await Promise.allSettled(
      fetchers.map((fetcher) =>
        fetcher({ api, signal: controller.signal, params, search: args.search }),
      ),
    );

    let unauthorized = false;
    const queries: SerializedQuery[] = [];

    for (const result of results) {
      if (result.status === 'fulfilled') {
        if (result.value) queries.push(result.value);
        continue;
      }

      if (isUnauthorized(result.reason)) {
        unauthorized = true;
        continue;
      }

      args.logger?.warn(
        { err: result.reason, pathname: args.pathname },
        'SSR prefetch fetcher failed (best-effort, ignoring)',
      );
    }

    if (unauthorized) {
      args.logger?.info(
        { pathname: args.pathname },
        'SSR prefetch saw 401 — dropping hydrated state, client will refetch',
      );
      return [];
    }

    return queries;
  } finally {
    clearTimeout(timer);
  }
}
