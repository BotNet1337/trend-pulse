/**
 * Aurora dark-only (TASK-074 landing). The marketing site is always dark to
 * match the SPA. The theme API is kept for compatibility, but resolves to
 * 'dark' unconditionally — there is no light mode and no stored preference.
 */
export type ThemeMode = 'system' | 'light' | 'dark';

export function getStoredTheme(): ThemeMode {
  return 'dark';
}

export function setStoredTheme(mode: ThemeMode) {
  void mode; // no-op: the site is always Aurora dark
}

export function resolveTheme(mode: ThemeMode): 'light' | 'dark' {
  void mode;
  return 'dark';
}

export function applyTheme(mode: ThemeMode) {
  void mode;
  // Always Aurora dark. Tailwind uses the `.dark` ancestor; we set it on both
  // <html> and <body> to avoid edge cases (mirrors the SSR theme-script).
  try {
    const root = document.documentElement;
    const body = document.body;
    root.classList.add('dark');
    body?.classList.add('dark');
    root.style.colorScheme = 'dark';
  } catch {
    // ignore
  }
}
