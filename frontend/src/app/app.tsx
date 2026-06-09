import React from 'react';
import type { QueryClient } from '@tanstack/react-query';
import AppProvider from './providers/app.provider';
import type { AuthStore } from './stores/auth.store';
import type { AlertStore } from './stores/alert.store';
import { AlertProvider } from './providers/alert.provider';
import QueryProvider from './providers/query.provider';
import { AppHealthProvider } from './providers/health.provider';
import { GlobalErrorBoundary } from '@/shared/components/global-error-boundary';

interface AppProps {
  auth: AuthStore;
  alert: AlertStore;
  /**
   * Pre-built QueryClient seeded from `__INITIAL_STATE__` (TASK-036). Optional
   * — when omitted, `QueryProvider` creates a fresh client. SSR omits this
   * because the server doesn't hydrate from the browser payload.
   */
  queryClient?: QueryClient;
  children: React.ReactNode;
}

const App: React.FC<AppProps> = (props) => {
  return (
    <GlobalErrorBoundary>
      <QueryProvider client={props.queryClient}>
        <AppHealthProvider>
          <AppProvider auth={props.auth}>
            <AlertProvider store={props.alert}>{props.children}</AlertProvider>
          </AppProvider>
        </AppHealthProvider>
      </QueryProvider>
    </GlobalErrorBoundary>
  );
};

export default App;
