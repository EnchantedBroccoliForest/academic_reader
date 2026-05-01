// Shared theme toggle for reader3.
// Cycles between "light" (default), "sepia", and "dark". Persists in localStorage.
(function () {
  'use strict';

  const STORAGE_KEY = 'reader3:theme';
  const THEMES = [
    { id: 'light', label: 'Light', icon: '\u2600\uFE0F' },
    { id: 'sepia', label: 'Sepia', icon: '\uD83D\uDCD6' },
    { id: 'dark',  label: 'Dark',  icon: '\uD83C\uDF19' },
  ];

  function getStoredTheme() {
    try { return localStorage.getItem(STORAGE_KEY) || 'light'; }
    catch (_) { return 'light'; }
  }

  function applyTheme(id) {
    if (id === 'light') {
      document.documentElement.removeAttribute('data-theme');
    } else {
      document.documentElement.setAttribute('data-theme', id);
    }
    try { localStorage.setItem(STORAGE_KEY, id); } catch (_) {}
    document.querySelectorAll('.theme-toggle button').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-theme') === id);
    });
  }

  function mountToggle() {
    if (document.querySelector('.theme-toggle')) return;
    const wrap = document.createElement('div');
    wrap.className = 'theme-toggle';
    wrap.setAttribute('role', 'group');
    wrap.setAttribute('aria-label', 'Color theme');
    THEMES.forEach(t => {
      const b = document.createElement('button');
      b.type = 'button';
      b.setAttribute('data-theme', t.id);
      b.setAttribute('title', t.label + ' theme');
      b.setAttribute('aria-label', t.label + ' theme');
      b.textContent = t.icon;
      b.addEventListener('click', () => applyTheme(t.id));
      wrap.appendChild(b);
    });
    document.body.appendChild(wrap);
    applyTheme(getStoredTheme());
  }

  // Apply theme as early as possible to avoid flash.
  applyTheme(getStoredTheme());

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mountToggle);
  } else {
    mountToggle();
  }
})();
