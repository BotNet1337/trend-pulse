/**
 * React-Query hooks for the TG pool admin UI (TASK-117, TASK-136).
 *
 * - usePoolHealth: light auto-refresh + manual refetch (snapshot is cheap but
 *   we avoid spamming — 15s background refresh).
 * - useQrLoginStart: mutation that begins a login and returns the QR payload.
 * - useQrLoginPoll: polls every ~2s while the status is non-terminal; stops
 *   automatically once a terminal status (success/expired/password_needed/error)
 *   is reached (refetchInterval returns false).
 * - useFactoryAccounts / useFactoryBudget: 15s-polling reads (TASK-136).
 * - useTriggerFactory: mutation that fires a factory tick and invalidates both
 *   factory query keys (GET /accounts and /budget) so the table refreshes.
 */

import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { getFactoryAccounts, getFactoryBudget, getPoolHealth, pollQrLogin, startQrLogin, triggerFactory } from './api';
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

// ─── Factory queries (TASK-136) ────────────────────────────────────────────────

/** Stable query key for the factory accounts list. */
export const FACTORY_ACCOUNTS_QUERY_KEY = ['admin', 'factory-accounts'] as const;

/** Stable query key for the factory budget. */
export const FACTORY_BUDGET_QUERY_KEY = ['admin', 'factory-budget'] as const;

/** Background refresh window for factory data (ms). */
export const FACTORY_REFETCH_MS = 15_000;

/**
 * Invalidate both factory query keys so the table and budget line refresh after a
 * trigger mutation. Idempotent: safe to call multiple times.
 */
export function invalidateFactory(queryClient: QueryClient): Promise<void[]> {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: FACTORY_ACCOUNTS_QUERY_KEY }),
    queryClient.invalidateQueries({ queryKey: FACTORY_BUDGET_QUERY_KEY }),
  ]);
}

/**
 * Query options for the factory accounts list (exported for unit tests).
 *
 * - `enabled`: superuser gate — regular users never fire the request.
 * - `retry: false`: 403/503 are terminal.
 * - `refetchInterval`: 15s background refresh mirrors pool-health.
 */
export function factoryAccountsQueryOptions(enabled: boolean) {
  return {
    queryKey: FACTORY_ACCOUNTS_QUERY_KEY,
    queryFn: getFactoryAccounts,
    refetchInterval: FACTORY_REFETCH_MS,
    retry: false,
    enabled,
  } as const;
}

/** Fetch the latest factory accounts list (superuser only). */
export function useFactoryAccounts(enabled: boolean) {
  return useQuery(factoryAccountsQueryOptions(enabled));
}

/**
 * Query options for the factory budget (exported for unit tests).
 *
 * - `enabled`: superuser gate.
 * - `retry: false`.
 * - `refetchInterval`: 15s background refresh.
 */
export function factoryBudgetQueryOptions(enabled: boolean) {
  return {
    queryKey: FACTORY_BUDGET_QUERY_KEY,
    queryFn: getFactoryBudget,
    refetchInterval: FACTORY_REFETCH_MS,
    retry: false,
    enabled,
  } as const;
}

/** Fetch the factory budget (superuser only). */
export function useFactoryBudget(enabled: boolean) {
  return useQuery(factoryBudgetQueryOptions(enabled));
}

/**
 * Mutation to trigger a factory provisioning tick.
 *
 * On success, invalidates both FACTORY_ACCOUNTS_QUERY_KEY and FACTORY_BUDGET_QUERY_KEY
 * so the panel reflects the new state within the next background poll. The trigger is
 * fire-and-forget (202): the backend dispatches a tick and the GET poll surfaces any
 * resulting state change.
 *
 * Callers should use `.mutate()` (not `.mutateAsync()`) so a rejected request (e.g. a
 * racy 503 when the provider was unset between the budget read and the click, or a 500
 * on the tick) is captured in the mutation's `isError`/`error` state instead of becoming
 * an unhandled promise rejection — explicit error handling at the boundary (CONVENTIONS).
 */
export function useTriggerFactory() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: triggerFactory,
    onSuccess: () => {
      void invalidateFactory(queryClient);
    },
  });
}
