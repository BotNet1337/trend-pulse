import * as React from 'react';
import { CookieBanner } from '@/shared/ui/cookie-banner';

export function AppShell(props: React.PropsWithChildren) {
  return (
    <>
      {props.children}
      <CookieBanner />
    </>
  );
}


