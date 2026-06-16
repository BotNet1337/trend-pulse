/**
 * TG pool admin API (TASK-117) — superuser-only QR login + pool health.
 *
 * Three endpoints from TASK-116 (under /api/v1/pool-admin). The server gate
 * (`current_superuser`, 401/403) is the only real protection; this client just
 * fetches after a 200. Types come ONLY from the generated OpenAPI schema (C1) —
 * no hand-rolled response shapes.
 */

import { apiClient } from '@/shared/api/client';
import type { components } from '@/shared/api/gen.types';

export type QrLoginStartResponse = components['schemas']['QRLoginStartResponse'];
export type QrLoginPollResponse = components['schemas']['QRLoginPollResponse'];
export type PoolHealthResponse = components['schemas']['PoolHealthResponse'];
export type PoolHealthAccount = components['schemas']['PoolHealthAccount'];

/** POST /pool-admin/qr-login/start — begin a QR login (no body). 503/429 on error. */
export async function startQrLogin(): Promise<QrLoginStartResponse> {
  const resp = await apiClient.post<QrLoginStartResponse>('/pool-admin/qr-login/start');
  return resp.data;
}

/**
 * GET /pool-admin/qr-login/{token} — poll an in-progress login.
 * Always 200 (unknown/expired token → status "expired"), so it is safe to poll
 * in a loop. `session_string` is present ONLY on status "success".
 */
export async function pollQrLogin(token: string): Promise<QrLoginPollResponse> {
  const resp = await apiClient.get<QrLoginPollResponse>(
    `/pool-admin/qr-login/${encodeURIComponent(token)}`,
  );
  return resp.data;
}

/** GET /pool-admin/pool-health — latest snapshot (200, incl. stale). 503 if Redis down. */
export async function getPoolHealth(): Promise<PoolHealthResponse> {
  const resp = await apiClient.get<PoolHealthResponse>('/pool-admin/pool-health');
  return resp.data;
}
