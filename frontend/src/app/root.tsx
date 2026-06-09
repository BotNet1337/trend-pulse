import './app.css';
import { createRoot } from 'react-dom/client';

import App from './app';
import { createAuthStore } from './stores/auth.store';
import { createAlertStore } from './stores/alert.store';
import { createAppRouter } from './router';
import { RouterProvider } from '@tanstack/react-router';
import { BRAND_NAME } from '@/shared/config';
import { createQueryClient } from './providers/query-client';

if (typeof document !== 'undefined' && document.title !== BRAND_NAME) {
  document.title = BRAND_NAME;
}

const auth = createAuthStore({ user: null });
const alert = createAlertStore();
const queryClient = createQueryClient();
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

createRoot(document.getElementById('root') as HTMLElement).render(
  <App auth={auth} alert={alert} queryClient={queryClient}>
    <RouterProvider router={router} />
  </App>,
);
