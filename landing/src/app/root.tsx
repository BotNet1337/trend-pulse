import { hydrateRoot } from 'react-dom/client';
import { RouterProvider } from '@tanstack/react-router';
import { createAppRouter } from './router/router';
import { AppShell } from './app';
import type { CaseItem } from '@/shared/cases/types';

const router = createAppRouter();

if (import.meta.env.DEV) {
  try {
    const root = document.documentElement;
    const styles = getComputedStyle(root);
    const bg = styles.getPropertyValue('--background')?.trim();
    const fg = styles.getPropertyValue('--foreground')?.trim();
    if (!bg || !fg) {
       
      console.warn('[landing] missing theme css vars', { '--background': bg, '--foreground': fg });
    }
  } catch {
    // ignore
  }
}

/**
 * TASK-068: hydrate the SAME tree the server rendered (render.tsx wraps the
 * router in <AppShell>). Before this fix the client hydrated a bare
 * <RouterProvider>, so the trees mismatched (React #418) and client-only UI
 * inside AppShell — the cookie banner — never mounted. Cases come from
 * window.__INITIAL_STATE__ (TASK-067 contract), the client never refetches.
 */
const initialState = (window as { __INITIAL_STATE__?: { cases?: CaseItem[] } }).__INITIAL_STATE__;

hydrateRoot(
  document.getElementById('root')!,
  <AppShell cases={initialState?.cases ?? []}>
    <RouterProvider router={router} />
  </AppShell>,
);


