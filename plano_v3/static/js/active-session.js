import {updateBreakTimer} from './break-alarm.js';
import {
  api,
  esc,
  validateTimer
} from './api.js';

const indicator = document.createElement('a');
indicator.className = 'active-session';
indicator.href = '/';
indicator.hidden = true;
indicator.setAttribute('aria-live', 'polite');
document.querySelector('.topbar').after(indicator);
const onToday = !!document.querySelector('#start-form');
let sequence = 0;
const channel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('plano-session') : null;

function render(timer) {
  updateBreakTimer(timer);
  indicator.hidden = !timer || !['running', 'paused'].includes(timer.status);
  if (indicator.hidden) return;
  const state = timer.recovery_required ? 'Conferir tempo da sessão' : timer.rest_active ? 'Intervalo programado' : timer.status === 'paused' ? 'Pausa curta' : 'Estudo em andamento';
  indicator.innerHTML = `<strong>${state}</strong><span>${esc(timer.title)}${timer.topic_name ? ' · ' + esc(timer.topic_name) : ''}</span><span>Voltar à sessão →</span>`;
}

export function publishTimer(timer) {
  ++sequence;
  render(timer);
}

export function notifySessionChange() {
  channel?.postMessage('changed');
}

async function refresh() {
  if (onToday) {
    window.dispatchEvent(new Event('session-refresh'));
    return;
  }
  const current = ++sequence;
  try {
    const timer = validateTimer(await api('/timer'), true);
    if (timer !== null && (!Number.isInteger(timer.id) || !['running', 'paused'].includes(timer.status))) throw new Error('Estado inválido');
    if (current === sequence) render(timer);
  } catch {
    if (current !== sequence) return;
    indicator.hidden = false;
    indicator.textContent = 'Não foi possível conferir a sessão. Abrir Hoje para reconectar →';
  }
}
channel?.addEventListener('message', refresh);
window.addEventListener('timer-state-changed',event=>{if(!onToday)publishTimer(event.detail);});
window.addEventListener('focus', refresh);
window.addEventListener('pageshow', refresh);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) refresh();
});
if (!onToday) {
  refresh();
  setInterval(() => {
    if (!document.hidden) refresh();
  }, 10000);
}
