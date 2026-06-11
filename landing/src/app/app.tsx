import * as React from 'react';
import { CookieBanner } from '@/shared/ui/cookie-banner';
import { CasesContext } from '@/shared/cases/cases-context';
import type { CaseItem } from '@/shared/cases/types';

export interface AppShellProps extends React.PropsWithChildren {
  /** TASK-067: SSR-fetched proof-of-speed cases (see shared/cases/cases-context). */
  cases?: CaseItem[];
}

export function AppShell(props: AppShellProps) {
  return (
    <CasesContext.Provider value={props.cases ?? []}>
      {props.children}
      <CookieBanner />
    </CasesContext.Provider>
  );
}
