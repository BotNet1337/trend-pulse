import type { JwtUser } from '../../entities/user/model';

/**
 * One TanStack Query cache entry serialized for client hydration.
 *
 * `key` MUST match the runtime query key produced by the corresponding
 * `*QueryKey` builder used by client hooks — otherwise hydration is a no-op
 * and the client refetches.
 */
export interface SerializedQuery {
  key: readonly unknown[];
  data: unknown;
}

/**
 * Shape of `window.__INITIAL_STATE__` injected by the SSR layer.
 *
 * Hydration is best-effort: any field may be missing if prefetch timed out
 * or upstream returned 401. The app must work without this object entirely.
 */
export interface InitialState {
  user: JwtUser | null;
  queries: SerializedQuery[];
}
