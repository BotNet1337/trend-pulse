import './app.css';
import { hydrateRoot } from 'react-dom/client';

import App from './app';
import { createAuthStore } from './stores/auth.store';
import { createAlertStore } from './stores/alert.store';
import { createAppRouter } from './router';
import { RouterClient } from '@tanstack/react-router/ssr/client';
import { BRAND_NAME } from '@/shared/config';
import { createQueryClient } from './providers/query-client';
import { hydrateQueryCache } from './hydrate-query-cache';

if (typeof document !== 'undefined' && document.title !== BRAND_NAME) {
  document.title = BRAND_NAME;
}

const initialState = window.__INITIAL_STATE__ ?? {};
const auth = createAuthStore({ user: initialState.user ?? null });
const alert = createAlertStore();

// Hydration MUST happen before the first render — otherwise the affected
// hooks tick over to `loading` for one frame and skeletons flash.
const queryClient = createQueryClient();
hydrateQueryCache(queryClient, initialState.queries);

const router = createAppRouter(auth);

// Dev-only escape hatch: lets local tooling (Claude Preview, Storybook, e2e
// scripts) flip auth state without going through a real sign-in. Stripped from
// production bundles by the import.meta.env.DEV check.
if (import.meta.env?.DEV) {
  (window as unknown as {
    __DEV_STORES__?: {
      auth: typeof auth;
      router: typeof router;
      queryClient: typeof queryClient;
    };
  }).__DEV_STORES__ = {
    auth,
    router,
    queryClient,
  };
}

hydrateRoot(
  document.getElementById('root') as HTMLElement,
  <App auth={auth} alert={alert} queryClient={queryClient}>
    <RouterClient router={router} />
  </App>,
);
