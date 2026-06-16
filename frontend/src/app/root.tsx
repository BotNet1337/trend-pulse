import './app.css';
import { hydrateRoot } from 'react-dom/client';

import App from './app';
import { createAuthStore } from './stores/auth.store';
import { createAlertStore } from './stores/alert.store';
import { createAppRouter } from './router';
// RouterClient is the SSR-hydration-aware counterpart to the server's
// `<RouterServer>` (server/ssr/render.tsx). Plain `RouterProvider` does NOT
// rehydrate the server-matched route, so the client renders a `<Suspense>`
// fallback where the server rendered the resolved route → a hydration mismatch
// (React #418) on every page. Pairing RouterServer↔RouterClient fixes it.
import { RouterClient } from '@tanstack/react-router/ssr/client';
import { BRAND_NAME } from '@/shared/config';
import { createQueryClient } from './providers/query-client';
import { hydrateQueryCache } from './hydrate-query-cache';
import type { InitialState } from '@/shared/ssr/initial-state.types';
import type { JwtUser } from '@/entities/user/model';

if (typeof document !== 'undefined' && document.title !== BRAND_NAME) {
  document.title = BRAND_NAME;
}

// ─── Hydrate from SSR __INITIAL_STATE__ ──────────────────────────────────────
// The SSR layer injects `window.__INITIAL_STATE__` via buildHtml / html.ts.
// Fields are optional (hydration is best-effort — anything missing is safe to
// ignore; the app falls back to client-side fetching).

const initialState: Partial<InitialState> | undefined =
  typeof window !== 'undefined' ? window.__INITIAL_STATE__ : undefined;

// Seed auth store from SSR user so that TanStack Router `beforeLoad` guards
// can read the user synchronously on the first render (avoids FOUC on guarded
// routes). The AuthProvider/AuthSync then keeps the store in sync via
// useCurrentUser (react-query).
const ssrUser: JwtUser | null = initialState?.user ?? null;

const auth = createAuthStore({ user: ssrUser });
const alert = createAlertStore();
const queryClient = createQueryClient();
const router = createAppRouter(auth);

// Seed the query cache from prefetched SSR data. Must happen BEFORE hydrateRoot
// so that hooks reading the cache during hydration see the same data as the
// server rendered — preventing hydration mismatches.
hydrateQueryCache(queryClient, initialState?.queries);

// Dev-only escape hatch: lets local tooling (Claude Preview, Storybook, e2e
// scripts) flip auth state without going through a real sign-in. Stripped from
// production bundles by the import.meta.env.DEV check. Does NOT affect prod
// hydration.
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

// hydrateRoot instead of createRoot — attaches React to the server-rendered
// DOM rather than replacing it. React will reconcile the existing HTML with
// the virtual DOM from the first render pass. Any mismatch between the server
// and client renders will produce a console warning (not a crash in prod, but
// a visible diff in dev).
hydrateRoot(
  document.getElementById('root') as HTMLElement,
  <App auth={auth} alert={alert} queryClient={queryClient}>
    <RouterClient router={router} />
  </App>,
);
