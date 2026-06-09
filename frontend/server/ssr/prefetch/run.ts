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
   * Raw `Cookie` request header from the inbound SSR request
   * (`req.headers.cookie`). Forwarded verbatim to the upstream API so that
   * the httpOnly `fastapiusersauth` cookie authenticates the prefetch calls.
   *
   * When undefined the upstream calls land unauthenticated, prefetch fetchers
   * return 401, and the runner drops all hydration to `[]`. The client will
   * see an empty cache and AuthGuard will redirect to /auth/sign-in.
   */
  cookieHeader: string | undefined;
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
 *   absent/stale and we don't want to render pre-authenticated content; the
 *   client will see an empty cache, refetch, and AuthGuard redirects to login.
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
      cookieHeader: args.cookieHeader,
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

      // Log only message/status — never the raw error object, whose axios
      // `config.headers` could carry the forwarded `Cookie` (session token).
      const reason: unknown = result.reason;
      const message = reason instanceof Error ? reason.message : String(reason);
      const status =
        typeof reason === 'object' && reason !== null && 'response' in reason
          ? (reason as { response?: { status?: number } }).response?.status
          : undefined;
      args.logger?.warn(
        { message, status, pathname: args.pathname },
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
