(() => {
  // Aurora dark-only (TASK-074 landing). The site is always dark to match the SPA.
  // We force the `.dark` class on first paint so Tailwind `dark:` variants resolve
  // to dark immediately — no FOUC, no broken light mode, regardless of any stored
  // theme preference or OS setting.
  try {
    document.documentElement.classList.add('dark');
    document.body && document.body.classList.add('dark');
    document.documentElement.style.colorScheme = 'dark';
  } catch {
    // ignore
  }
})();
