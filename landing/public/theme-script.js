(() => {
  try {
    const stored = localStorage.getItem('theme'); // 'light' | 'dark' | 'system' | null
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    const resolved = stored === 'light' || stored === 'dark' ? stored : prefersDark ? 'dark' : 'light';
    if (resolved === 'dark') {
      document.documentElement.classList.add('dark');
      document.body && document.body.classList.add('dark');
      document.documentElement.style.colorScheme = 'dark';
    } else {
      document.documentElement.classList.remove('dark');
      document.body && document.body.classList.remove('dark');
      document.documentElement.style.colorScheme = 'light';
    }
  } catch {
    // ignore
  }
})();


