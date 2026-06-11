/**
 * Admin business-metrics API — superuser-only money dashboard (TASK-063).
 *
 * Single endpoint from TASK-051: GET /ops/business-metrics. The server gate
 * (`current_superuser`, 401/403) is the only real protection; this client just
 * fetches after a 200. Types come ONLY from the generated OpenAPI schema (C1).
 */

import { apiClient } from '@/shared/api/client';
import type { components } from '@/shared/api/gen.types';

export type BusinessMetricsResponse = components['schemas']['BusinessMetricsResponse'];
export type FunnelSummary = components['schemas']['FunnelSummary'];
export type FunnelDayRow = components['schemas']['FunnelDayRow'];

/** GET /ops/business-metrics — aggregate snapshot (superuser only, 403 otherwise). */
export async function getBusinessMetrics(): Promise<BusinessMetricsResponse> {
  const resp = await apiClient.get<BusinessMetricsResponse>('/ops/business-metrics');
  return resp.data;
}
