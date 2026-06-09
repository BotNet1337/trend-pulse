/**
 * Alerts API calls — all via apiClient (cookie-auth, baseURL=/api).
 * Endpoints: GET /alerts (list + pagination), GET /alerts/{id} (detail).
 * Types from gen.types (C1 invariant — regenerated after adding GET /alerts).
 */

import { apiClient } from '@/shared/api/client';
import type { AlertListResponse, AlertRead } from '@/entities/alert/model';

export interface ListAlertsParams {
  limit?: number;
  offset?: number;
}

/** GET /alerts — returns paginated AlertListResponse (tenant-scoped). */
export async function listAlerts(params: ListAlertsParams = {}): Promise<AlertListResponse> {
  const resp = await apiClient.get<AlertListResponse>('/alerts', { params });
  return resp.data;
}

/** GET /alerts/{id} — 404 on missing or other tenant's. */
export async function getAlert(id: number): Promise<AlertRead> {
  const resp = await apiClient.get<AlertRead>(`/alerts/${id}`);
  return resp.data;
}
