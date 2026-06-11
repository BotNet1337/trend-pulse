/**
 * Alerts API calls — all via apiClient (cookie-auth, baseURL=/api).
 * Endpoints: GET /alerts (list + cursor pagination), GET /alerts/{id} (detail).
 * Types from gen.types (C1 invariant — regenerated after cursor pagination TASK-020).
 */

import { apiClient } from '@/shared/api/client';
import type { AlertListResponse, AlertRead } from '@/entities/alert/model';

export interface ListAlertsParams {
  cursor?: string;
  limit?: number;
}

/** GET /alerts — returns cursor-paginated AlertListResponse (tenant-scoped). */
export async function listAlerts(params: ListAlertsParams = {}): Promise<AlertListResponse> {
  const resp = await apiClient.get<AlertListResponse>('/alerts', { params });
  return resp.data;
}

/** GET /alerts/{id} — 404 on missing or other tenant's. */
export async function getAlert(id: number): Promise<AlertRead> {
  const resp = await apiClient.get<AlertRead>(`/alerts/${id}`);
  return resp.data;
}

/**
 * Record alert feedback via the shared TASK-042 write-path.
 *
 * The token (minted server-side in the alert detail response) is the sole
 * bearer credential. The endpoint lives under the same `/api/v1` base as the
 * alerts routes (apiClient.baseURL='/api/v1'), so the relative path is
 * `/feedback/${token}` → full URL `/api/v1/feedback/{token}`. Success is HTTP
 * 200; the response body is HTML (for Telegram users) and is ignored here.
 */
export async function sendFeedback(token: string): Promise<void> {
  await apiClient.get(`/feedback/${token}`);
}
