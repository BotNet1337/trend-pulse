/**
 * Packs API calls — all via apiClient (cookie-auth, baseURL=/api).
 * Endpoints from TASK-038: GET /packs, POST/DELETE /packs/{slug}/subscribe.
 */

import { apiClient } from '@/shared/api/client';
import type { components } from '@/shared/api/gen.types';

export type PackRead = components['schemas']['PackRead'];
export type SubscribeResult = components['schemas']['SubscribeResult'];
export type UnsubscribeResult = components['schemas']['UnsubscribeResult'];

/** GET /packs — returns the curated pack catalog (auth required). */
export async function listPacks(): Promise<PackRead[]> {
  const resp = await apiClient.get<PackRead[]>('/packs');
  return resp.data;
}

/** POST /packs/{slug}/subscribe — subscribe in 1 click; idempotent. */
export async function subscribePack(slug: string): Promise<SubscribeResult> {
  const resp = await apiClient.post<SubscribeResult>(`/packs/${slug}/subscribe`);
  return resp.data;
}

/** DELETE /packs/{slug}/subscribe — unsubscribe; deleted=0 if not subscribed. */
export async function unsubscribePack(slug: string): Promise<UnsubscribeResult> {
  const resp = await apiClient.delete<UnsubscribeResult>(`/packs/${slug}/subscribe`);
  return resp.data;
}
