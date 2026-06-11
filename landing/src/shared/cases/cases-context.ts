import * as React from 'react';
import type { CaseItem } from './types';

/**
 * TASK-067: proof-of-speed cases context.
 * SSR: `server/ssr/render.tsx` wraps the tree in <AppShell cases={…}> which
 * provides the server-fetched list.
 * Client: there is no AppShell around <RouterProvider> (see src/app/root.tsx),
 * so the context DEFAULT is hydrated from window.__INITIAL_STATE__ — the inline
 * state script runs before the module bundle, and the client never refetches,
 * which keeps client markup identical to SSR markup (no hydration mismatch).
 */
function readCasesFromInitialState(): CaseItem[] {
  const state = (window as { __INITIAL_STATE__?: { cases?: unknown } }).__INITIAL_STATE__;
  return Array.isArray(state?.cases) ? (state.cases as CaseItem[]) : [];
}

export const CasesContext = React.createContext<CaseItem[]>(
  typeof window === 'undefined' ? [] : readCasesFromInitialState(),
);

export function useCases(): CaseItem[] {
  return React.useContext(CasesContext);
}
