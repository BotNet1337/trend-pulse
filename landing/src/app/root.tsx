import { hydrateRoot } from 'react-dom/client';
import { RouterProvider } from '@tanstack/react-router';
import { createAppRouter } from './router/router';

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

hydrateRoot(document.getElementById('root')!, <RouterProvider router={router} />);


