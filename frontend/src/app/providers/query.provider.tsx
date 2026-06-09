import React, { useEffect, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { createQueryClient } from './query-client';

export interface QueryProviderProps {
  /**
   * Optional pre-configured client. The bootstrap (`root.tsx`) creates one
   * outside React to hydrate the cache from `__INITIAL_STATE__` BEFORE the
   * first render. When omitted, a default client is created here — used
   * by SSR and by callers that don't care about hydration.
   */
  client?: QueryClient;
  children: React.ReactNode;
}

const QueryProvider: React.FC<QueryProviderProps> = ({ client, children }) => {
  const [queryClient] = useState(() => client ?? createQueryClient());

  useEffect(() => {
    if (import.meta.env?.DEV && typeof window !== 'undefined') {
      (window as unknown as { __DEV_QUERY_CLIENT__?: QueryClient }).__DEV_QUERY_CLIENT__ = queryClient;
    }
  }, [queryClient]);

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

export default QueryProvider;
