/**
 * API-keys API calls (TASK-065) — all via apiClient (cookie-auth, baseURL=/api/v1).
 * Endpoints from TASK-028: GET/POST /api-keys, DELETE /api-keys/{key_id}.
 *
 * INVARIANT (plaintext exactly once): `ApiKeyCreated.key` is the only carrier of
 * the plaintext. Callers must keep it in transient local state (created-key
 * modal) — never in the react-query cache, localStorage, URL, or logs.
 */

import { apiClient } from '@/shared/api/client';
import type { components } from '@/shared/api/gen.types';

export type ApiKeyRead = components['schemas']['ApiKeyRead'];
export type ApiKeyCreated = components['schemas']['ApiKeyCreated'];
export type ApiKeyCreate = components['schemas']['ApiKeyCreate'];

/** GET /api-keys — list own keys (masked: prefix only, no plaintext). */
export async function listApiKeys(): Promise<ApiKeyRead[]> {
  const resp = await apiClient.get<ApiKeyRead[]>('/api-keys');
  return resp.data;
}

/**
 * POST /api-keys — issue a new key. Response carries the plaintext EXACTLY ONCE.
 * 403 PlanLimitExceeded for plans without API access (server-side gate).
 */
export async function createApiKey(name: string): Promise<ApiKeyCreated> {
  const body: ApiKeyCreate = { name };
  const resp = await apiClient.post<ApiKeyCreated>('/api-keys', body);
  return resp.data;
}

/** DELETE /api-keys/{key_id} — soft-revoke; 204 on success, 404 if unknown/foreign. */
export async function revokeApiKey(keyId: number): Promise<void> {
  await apiClient.delete<void>(`/api-keys/${keyId}`);
}
