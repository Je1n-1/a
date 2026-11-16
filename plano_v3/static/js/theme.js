import {icon} from './icons.js';
const button = document.querySelector('#theme-toggle');
function paint() {
  const dark = document.documentElement.dataset.theme !== 'light';
  button.innerHTML = icon(dark ? 'sun' : 'moon');
  button.setAttribute('aria-label', dark ? 'Tema escuro. Ativar tema claro' : 'Tema claro. Ativar tema escuro');
  button.setAttribute('aria-pressed', String(!dark));
  button.title = dark ? 'Ativar tema claro' : 'Ativar tema escuro';
}
button.addEventListener('click', () => {
  const theme = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem('plano.theme', theme); } catch {}
  paint();
});
window.addEventListener('storage', event => {
  if (event.key !== 'plano.theme') return;
  document.documentElement.dataset.theme = event.newValue === 'light' ? 'light' : 'dark';
  paint();
});
paint();
