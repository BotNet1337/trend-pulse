/**
 * Watchlist API calls — all via apiClient (cookie-auth, baseURL=/api).
 * Endpoints from task-004: GET/POST /watchlists, GET/PATCH/DELETE /watchlists/{id}.
 */

import { apiClient } from '@/shared/api/client';
import type { WatchlistRead, WatchlistCreate, WatchlistUpdate } from '@/entities/watchlist/model';

/** GET /watchlists — returns caller's watchlists (tenant-scoped). */
export async function listWatchlists(): Promise<WatchlistRead[]> {
  const resp = await apiClient.get<WatchlistRead[]>('/watchlists');
  return resp.data;
}

/** GET /watchlists/{id} — 404 on missing or other tenant's. */
export async function getWatchlist(id: number): Promise<WatchlistRead> {
  const resp = await apiClient.get<WatchlistRead>(`/watchlists/${id}`);
  return resp.data;
}

/** POST /watchlists → 201 WatchlistRead; 402/403/422/409 errors. */
export async function createWatchlist(payload: WatchlistCreate): Promise<WatchlistRead> {
  const resp = await apiClient.post<WatchlistRead>('/watchlists', payload);
  return resp.data;
}

/** PATCH /watchlists/{id} — partial update; 404 on missing. */
export async function updateWatchlist(
  id: number,
  payload: WatchlistUpdate,
): Promise<WatchlistRead> {
  const resp = await apiClient.patch<WatchlistRead>(`/watchlists/${id}`, payload);
  return resp.data;
}

/** DELETE /watchlists/{id} → 204; 404 on missing. */
export async function deleteWatchlist(id: number): Promise<void> {
  await apiClient.delete(`/watchlists/${id}`);
}
