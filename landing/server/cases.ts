import { z } from 'zod';
import type { CaseItem } from '../src/shared/cases/types';

/**
 * TASK-067: typed fetch of public `GET /api/v1/cases` with an in-memory cache.
 *
 * Invariants (see docs/tasks/task-067-landing-cases-showcase-link.md):
 * - never throws into the SSR path — any failure (timeout, HTTP error, bad
 *   JSON, schema drift) is logged and yields `[]`;
 * - at most ~1 upstream request per TTL window: both successful and failed
 *   results are cached until the TTL expires (no stale-while-revalidate);
 * - empty `apiUrl` = feature disabled, no request is ever made.
 */

const MS_PER_SECOND = 1000;

const caseItemSchema = z.object({
  title: z.string(),
  viral_score: z.number(),
  first_seen: z.string(),
  mainstream_at: z.string(),
  lead_time_seconds: z.number(),
  channels_count: z.number(),
});

const casesResponseSchema = z.object({
  items: z.array(caseItemSchema),
});

export interface CasesLogger {
  warn: (obj: Record<string, unknown>, msg: string) => void;
}

export interface CasesServiceOptions {
  /** Absolute URL of the cases endpoint; empty string disables fetching. */
  apiUrl: string;
  cacheTtlSeconds: number;
  fetchTimeoutMs: number;
  /** Injectable for tests; defaults to global fetch. */
  fetchImpl?: typeof fetch;
  logger?: CasesLogger;
  /** Injectable clock for tests; returns epoch milliseconds. */
  now?: () => number;
}

export interface CasesService {
  getCases: () => Promise<CaseItem[]>;
}

interface CacheEntry {
  items: CaseItem[];
  fetchedAtMs: number;
}

export function createCasesService(options: CasesServiceOptions): CasesService {
  const fetchImpl = options.fetchImpl ?? fetch;
  const now = options.now ?? Date.now;
  const ttlMs = options.cacheTtlSeconds * MS_PER_SECOND;

  let cache: CacheEntry | null = null;
  let inflight: Promise<CaseItem[]> | null = null;

  async function fetchCases(): Promise<CaseItem[]> {
    try {
      const response = await fetchImpl(options.apiUrl, {
        signal: AbortSignal.timeout(options.fetchTimeoutMs),
        headers: { accept: 'application/json' },
      });
      if (!response.ok) {
        options.logger?.warn({ status: response.status, url: options.apiUrl }, 'cases_fetch_http_error');
        return [];
      }
      const parsed = casesResponseSchema.safeParse(await response.json());
      if (!parsed.success) {
        options.logger?.warn({ issues: parsed.error.issues.slice(0, 3) }, 'cases_fetch_invalid_schema');
        return [];
      }
      return parsed.data.items;
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      options.logger?.warn({ error: message, url: options.apiUrl }, 'cases_fetch_failed');
      return [];
    }
  }

  return {
    async getCases(): Promise<CaseItem[]> {
      if (options.apiUrl === '') return [];

      const nowMs = now();
      if (cache && nowMs - cache.fetchedAtMs < ttlMs) {
        return cache.items;
      }
      if (inflight) return inflight;

      inflight = fetchCases()
        .then((items) => {
          cache = { items, fetchedAtMs: now() };
          return items;
        })
        .finally(() => {
          inflight = null;
        });
      return inflight;
    },
  };
}
