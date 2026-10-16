export const $ = (s, root = document) => root.querySelector(s);
export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;'
} [c]));
export const labels = {
  not_available: 'Não iniciada',
  available: 'Disponível',
  in_progress: 'Em andamento',
  completed: 'Concluída',
  failed: 'Reprovada',
  locked: 'Bloqueada',
  exempted: 'Dispensada'
};
export const duration = seconds => {
  const s = Math.max(0, Math.floor(seconds || 0));
  return s >= 3600 ? `${Math.floor(s/3600)} h ${Math.floor(s%3600/60)} min` : s >= 60 ? `${Math.floor(s/60)} min` : `${s} s`;
};
export async function api(path, options = {}) {
  let response;
  try {
    response = await fetch('/api' + path, {
      ...options,
      headers: {
        ...(options.body instanceof FormData ? {} : {
          'Content-Type': 'application/json'
        }),
        ...options.headers
      }
    });
  } catch {
    throw new Error('Não foi possível conectar. Confira se o Plano está aberto e tente novamente.');
  }
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error('O servidor devolveu uma resposta inesperada. Tente novamente.');
  }
  if (!response.ok) {
    const error = new Error(data.error || 'Não foi possível concluir.');
    error.status = response.status;
    throw error;
  }
  return data;
}
export const send = (path, body, method = 'POST') => api(path, {
  method,
  body: JSON.stringify(body)
});
export function validateTimer(value, allowEmpty = false) {
  if (allowEmpty && value === null) return value;
  if (!value || !Number.isInteger(value.id) || !Number.isInteger(value.version) ||
    !['running', 'paused', 'completed', 'cancelled'].includes(value.status) ||
    typeof value.title !== 'string' ||
    !Number.isFinite(value.effective_seconds) || !Number.isFinite(value.break_seconds)) {
    throw new Error('Não foi possível confirmar o estado do relógio. Atualize a sessão para conferir.');
  }
  return value;
}
let toastTimer;
export function toast(message) {
  $('#notifications').textContent = message;
  $('#notifications').classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('#notifications').classList.remove('visible'), 6000);
}
export function dialog(title, content, onSave, button = 'Salvar') {
  const el = $('#common-dialog');
  el.innerHTML = `<form method="dialog"><header class="dialog-heading"><h2>${esc(title)}</h2><button type="button" class="icon-button" data-close aria-label="Fechar">×</button></header><div class="dialog-content">${content}</div><p class="form-error" role="alert"></p><div class="dialog-actions"><button type="button" class="button secondary" data-close>Cancelar</button>${onSave?`<button class="button primary" type="submit">${esc(button)}</button>`:''}</div></form>`;
  el.querySelectorAll('[data-close]').forEach(b => b.onclick = () => el.close());
  const form = $('form', el);
  let busy = false;
  el.oncancel = e => {
    if (busy) e.preventDefault();
  };
  form.onsubmit = async e => {
    e.preventDefault();
    if (!onSave || busy) return;
    busy = true;
    const buttons = [...el.querySelectorAll('button')];
    buttons.forEach(b => b.disabled = true);
    $('.form-error', el).textContent = '';
    try {
      await onSave(Object.fromEntries(new FormData(form)));
      el.close();
    } catch (error) {
      $('.form-error', el).textContent = error.message;
    } finally {
      busy = false;
      buttons.forEach(b => b.disabled = false);
    }
  };
  el.showModal();
  return el;
}
export async function studyNow(subjectId) {
  location.href = '/?subject=' + encodeURIComponent(subjectId);
}
