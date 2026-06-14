import * as React from 'react';
import { applyTheme } from '@/shared/site/theme';

/**
 * Aurora dark-only (TASK-074 landing). The site no longer offers a light mode,
 * so the toggle renders nothing — it only re-asserts the Aurora dark class on
 * mount as a belt-and-suspenders against any stale state. Kept as a component
 * so the existing header/nav markup is unchanged.
 */
export function ThemeToggle() {
  React.useEffect(() => {
    applyTheme('dark');
  }, []);

  return null;
}
