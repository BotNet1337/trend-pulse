(function() {
  try {
    var storageKey = 'theme';
    var theme = localStorage.getItem(storageKey);
    var supportDarkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;
    
    var isDark = theme === 'dark' || (!theme && supportDarkMode) || (theme === 'system' && supportDarkMode);
    
    if (isDark) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  } catch (e) {}
})();

