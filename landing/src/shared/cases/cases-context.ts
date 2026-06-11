import * as React from 'react';
import type { CaseItem } from './types';

/**
 * TASK-067: proof-of-speed cases context.
 * SSR: `server/ssr/render.tsx` wraps the tree in <AppShell cases={…}> which
 * provides the server-fetched list.
 * Client: since TASK-068 `src/app/root.tsx` hydrates the same <AppShell> with
 * cases read from window.__INITIAL_STATE__ (the inline state script runs before
 * the module bundle; the client never refetches). The context DEFAULT below
 * also reads the initial state as a safety net for any tree rendered outside
 * AppShell.
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
