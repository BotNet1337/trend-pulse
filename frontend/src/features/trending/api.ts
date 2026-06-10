/**
 * Trending API calls (TASK-039) — GET /trending?pack=&limit=
 * Auth required; no plan gate (showcase data, not user history).
 */

import { apiClient } from '@/shared/api/client';
import type { components } from '@/shared/api/gen.types';

export type TrendingItem = components['schemas']['TrendingItem'];
export type TrendingResponse = components['schemas']['TrendingResponse'];

/**
 * GET /trending?pack=<slug>&limit=<n>
 * Returns top-K showcase viral clusters for the given pack (24h window).
 */
export async function getTrending(pack: string, limit?: number): Promise<TrendingResponse> {
  const params: Record<string, string | number> = { pack };
  if (limit !== undefined) {
    params['limit'] = limit;
  }
  const resp = await apiClient.get<TrendingResponse>('/trending', { params });
  return resp.data;
}
