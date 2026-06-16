/**
 * React-Query hooks for the TG pool admin UI (TASK-117).
 *
 * - usePoolHealth: light auto-refresh + manual refetch (snapshot is cheap but
 *   we avoid spamming — 15s background refresh).
 * - useQrLoginStart: mutation that begins a login and returns the QR payload.
 * - useQrLoginPoll: polls every ~2s while the status is non-terminal; stops
 *   automatically once a terminal status (success/expired/password_needed/error)
 *   is reached (refetchInterval returns false).
 */

import { useMutation, useQuery, type QueryClient } from '@tanstack/react-query';
import { getPoolHealth, pollQrLogin, startQrLogin } from './api';
import { asQrLoginStatus, isTerminalQrStatus } from './lib';

/** Stable query key for the pool-health snapshot. */
export const POOL_HEALTH_QUERY_KEY = ['admin', 'pool-health'] as const;

/**
 * Invalidate the pool-health snapshot so the table refetches after a successful QR
 * login (TASK-120). The worker applies the revive/add on its next tick, so the freshest
 * snapshot reflects the row flipping to Connected within ~one cycle — an HONEST refetch,
 * never a fake optimistic flip. Idempotent: a repeated SUCCESS poll just re-invalidates.
 */
export function invalidatePoolHealth(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: POOL_HEALTH_QUERY_KEY });
}

/** Stable query key factory for a single QR-login poll (keyed by token). */
export const qrLoginPollQueryKey = (token: string) =>
  ['admin', 'qr-login', token] as const;

/** Background refresh window for the pool-health snapshot (ms). */
const POOL_HEALTH_REFETCH_MS = 15_000;

/** QR poll cadence while the login is non-terminal (ms). */
const QR_POLL_INTERVAL_MS = 2_000;

/**
 * Query options for the pool-health snapshot (exported for unit tests).
 *
 * - `enabled`: the page passes `is_superuser === true` so the request never
 *   fires for regular users (client-side UX guard).
 * - `retry: false`: 403/503 are terminal here — retrying just spams the gate.
 * - `refetchInterval`: light background refresh; the page also exposes a manual
 *   refetch button.
 */
export function poolHealthQueryOptions(enabled: boolean) {
  return {
    queryKey: POOL_HEALTH_QUERY_KEY,
    queryFn: getPoolHealth,
    refetchInterval: POOL_HEALTH_REFETCH_MS,
    retry: false,
    enabled,
  } as const;
}

/** Fetch the latest pool-health snapshot (superuser only). */
export function usePoolHealth(enabled: boolean) {
  return useQuery(poolHealthQueryOptions(enabled));
}

/** Start a QR login — POST /pool-admin/qr-login/start. */
export function useQrLoginStart() {
  return useMutation({
    mutationFn: startQrLogin,
  });
}

/**
 * Query options for polling a QR login (exported for unit tests).
 *
 * `refetchInterval` is a function: poll every 2s while pending, then return
 * `false` once the latest status is terminal — this is the flow's stop
 * condition (no separate timer, no leaked interval).
 */
export function qrLoginPollQueryOptions(token: string | null) {
  return {
    queryKey: qrLoginPollQueryKey(token ?? ''),
    queryFn: () => pollQrLogin(token as string),
    enabled: token !== null,
    retry: false,
    refetchInterval: (query: {
      state: { data?: { status: string } | undefined };
    }): number | false => {
      const status = query.state.data?.status;
      if (status === undefined) return QR_POLL_INTERVAL_MS;
      return isTerminalQrStatus(asQrLoginStatus(status)) ? false : QR_POLL_INTERVAL_MS;
    },
  } as const;
}

/** Poll a QR login while non-terminal; `null` token disables the query. */
export function useQrLoginPoll(token: string | null) {
  return useQuery(qrLoginPollQueryOptions(token));
}
