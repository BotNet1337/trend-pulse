import * as React from 'react';
import { Moon, Sun, Monitor } from 'lucide-react';
import { Button } from '@/shared/components/button';
import { applyTheme, getStoredTheme, resolveTheme, setStoredTheme, type ThemeMode } from '@/shared/site/theme';

export function ThemeToggle() {
  const [mounted, setMounted] = React.useState(false);
  const [mode, setMode] = React.useState<ThemeMode>('system');

  React.useEffect(() => {
    setMounted(true);
    const stored = getStoredTheme();
    setMode(stored);
    applyTheme(stored);

    const mq = window.matchMedia?.('(prefers-color-scheme: dark)');
    const onChange = () => {
      const current = getStoredTheme();
      if (current === 'system') applyTheme('system');
    };
    mq?.addEventListener?.('change', onChange);
    return () => mq?.removeEventListener?.('change', onChange);
  }, []);

  if (!mounted) return null;

  const resolved = resolveTheme(mode);
  const Icon = mode === 'system' ? Monitor : resolved === 'dark' ? Moon : Sun;
  const label = mode === 'system' ? 'System' : resolved === 'dark' ? 'Dark' : 'Light';

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      aria-label={`Theme: ${label}. Click to change.`}
      onClick={() => {
        const next: ThemeMode = mode === 'system' ? 'light' : mode === 'light' ? 'dark' : 'system';
        setMode(next);
        setStoredTheme(next);
        applyTheme(next);
      }}
    >
      <Icon className="h-4 w-4" />
    </Button>
  );
}


