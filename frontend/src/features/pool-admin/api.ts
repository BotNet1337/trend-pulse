/**
 * TG pool admin API (TASK-117, TASK-136) — superuser-only QR login, pool health,
 * and account factory endpoints.
 *
 * Endpoints under /api/v1/pool-admin and /api/v1/factory. The server gate
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

// ─── Factory API types (TASK-136) ─────────────────────────────────────────────

/** A single factory account row from GET /factory/accounts. */
export type FactoryAccount = components['schemas']['FactoryAccountOut'];
/** Budget math from GET /factory/budget. */
export type FactoryBudget = components['schemas']['BudgetOut'];
/** POST /factory/accounts trigger summary (202). */
export type FactoryTrigger = components['schemas']['FactoryTriggerOut'];

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

// ─── Factory endpoints (TASK-136, under /v1/factory) ──────────────────────────

/** GET /factory/accounts — all factory accounts across every state. Read-only, no provider gate. */
export async function getFactoryAccounts(): Promise<FactoryAccount[]> {
  const resp = await apiClient.get<FactoryAccount[]>('/factory/accounts');
  return resp.data;
}

/** GET /factory/budget — budget math (enabled=false when provider unset). No provider gate. */
export async function getFactoryBudget(): Promise<FactoryBudget> {
  const resp = await apiClient.get<FactoryBudget>('/factory/budget');
  return resp.data;
}

/**
 * POST /factory/accounts — trigger a factory provisioning tick.
 * Returns 202 + { status: "triggered" }. 503 when provider unset.
 * Fire-and-forget: poll GET /factory/accounts to observe state changes.
 */
export async function triggerFactory(): Promise<FactoryTrigger> {
  const resp = await apiClient.post<FactoryTrigger>('/factory/accounts');
  return resp.data;
}

/**
 * POST /factory/accounts/{accountId}/relogin — re-trigger provisioning for one account.
 * Returns 202. 503 when provider unset; 404 when account not found.
 */
export async function reloginFactory(accountId: number): Promise<FactoryTrigger> {
  const resp = await apiClient.post<FactoryTrigger>(`/factory/accounts/${accountId}/relogin`);
  return resp.data;
}
