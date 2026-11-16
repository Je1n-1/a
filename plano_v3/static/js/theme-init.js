// Run before stylesheets: no inline script and no request outside this computer.
(() => {
  let theme = 'dark';
  try { const saved = localStorage.getItem('plano.theme'); if (saved === 'light' || saved === 'dark') theme = saved; } catch {}
  document.documentElement.dataset.theme = theme;
})();
