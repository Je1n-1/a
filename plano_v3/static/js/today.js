import {
  $,
  esc,
  api,
  send,
  toast,
  dialog,
  duration
} from './api.js';
import {
  clock,
  localInput
} from './study-format.js';
let subjects = [],
  courses = [],
  timer = null,
  received = 0,
  busy = false,
  operationKey = crypto.randomUUID(),
  generation = 0,
  loaded = false;
const liveSeconds = () => Math.max(0, Math.floor((performance.now() - received) / 1000));
const elapsed = () => timer ? timer.effective_seconds + (timer.status === 'running' ? liveSeconds() : 0) : 0;
const pauses = () => timer ? timer.break_seconds + (timer.status === 'paused' ? liveSeconds() : 0) : 0;
const isActive = data => data && ['running', 'paused'].includes(data.status);

function accept(data) {
  timer = isActive(data) ? data : null;
  received = performance.now();
  paint();
}

function tick() {
  const seconds = elapsed();
  $('#elapsed').textContent = [Math.floor(seconds / 3600), Math.floor(seconds % 3600 / 60), seconds % 60].map(n => String(n).padStart(2, '0')).join(':');
  $('#effective').textContent = duration(seconds);
  $('#breaks').textContent = duration(pauses());
  $('#clock-progress').style.strokeDashoffset = String(898.5 * (1 - (seconds % 3600) / 3600));
}

function paint() {
  $('#timer-status').textContent = timer ? (timer.status === 'paused' ? 'Em pausa' : 'Em estudo') : 'Pronto para começar';
  $('#timer-status').classList.toggle('green', timer?.status === 'running');
  $('#clock-hint').textContent = timer ? (timer.status === 'paused' ? 'Respire. O estudo está pausado.' : 'Um minuto de cada vez.') : 'Seu próximo passo começa aqui.';
  $('#active-title').innerHTML = timer ? `<strong>${esc(timer.title)}</strong><small>${esc(timer.course_name||'Estudo avulso')}</small>` : '';
  $('#selection-card').hidden = !!timer;
  const needsReview = timer?.recovery_required;
  $('#recovery-notice').hidden = !needsReview;
  $('#recovery-notice').textContent = needsReview ? 'Esta sessão está aberta há 8 horas ou mais desde a última confirmação. Revise o período antes de retomar ou finalizar.' : '';
  $('#timer-actions').innerHTML = timer ? `
  <button class="button secondary" data-action="${timer.status==='paused'?'resume':'pause'}" ${needsReview&&timer.status==='paused'?'disabled':''}>${timer.status==='paused'?'▶ Retomar':'Ⅱ Pausar'}</button>
  <button class="button primary" data-action="${needsReview?'recover':'finish'}">${needsReview?'Revisar período':'✓ Finalizar'}</button>
  ${needsReview?'':'<button class="button ghost" data-action="recover">Revisar período</button>'}
  <button class="button ghost" data-action="cancel">Descartar</button>` : '<span class="muted">Escolha seu foco para iniciar.</span>';
  if (busy) $('#timer-actions').querySelectorAll('button').forEach(b => b.disabled = true);
  tick();
}

function choices() {
  const course = $('#today-course').value,
    previous = $('#today-subject').value;
  const rows = subjects.filter(s => !course || s.course_id === Number(course));
  $('#today-subject').innerHTML = '<option value="">Selecione uma disciplina</option>' + rows.map(s => `<option value="${s.id}">${esc(s.name)}${!course?' · '+esc(s.course_name):''}</option>`).join('') + '<option value="free">Estudo avulso</option>';
  if ([...$('#today-subject').options].some(o => o.value === previous)) $('#today-subject').value = previous;
  $('#free-label').hidden = $('#today-subject').value !== 'free';
  $('#start-button').disabled = false;
}
const dateLabel = r => r.started_at ? new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'America/Sao_Paulo'
}).format(new Date(r.started_at)) : r.local_date.split('-').reverse().join('/');

function paintRecent({
  recent: rows,
  summary: totals
}) {
  $('#today-total').textContent = clock(totals.today.effective_seconds);
  $('#week-total').textContent = clock(totals.week.effective_seconds);
  $('#recent').innerHTML = rows.length ? rows.map(r => `<article class="recent-item"><div><strong>${esc(r.title)}</strong><small>${esc(r.course_name||'Estudo avulso')} · ${esc(dateLabel(r))} · ${r.source==='manual'?(r.started_at?'Horários informados manualmente':'Duração informada manualmente'):'Cronômetro'}</small>${r.note?`<p>${esc(r.note)}</p>`:''}<button class="inline-link" data-session="${r.id}">Ver divisão por dia</button></div><div class="recent-time">${duration(r.effective_seconds)}<small>${duration(r.break_seconds)} de pausa</small></div></article>`).join('') : '<div class="empty"><h3>Sua primeira sessão começa hoje.</h3><p>Ao finalizar o relógio, o tempo e suas anotações aparecem aqui.</p></div>';
}
async function recent() {
  paintRecent(await api('/today?catalog=0'));
}
async function refresh() {
  if (!loaded) return init();
  if (busy) return;
  const sequence = ++generation;
  try {
    const data = await api('/timer');
    if (sequence !== generation || busy) return;
    const changed = timer?.id !== data?.id || timer?.version !== data?.version || timer?.recovery_required !== data?.recovery_required;
    timer = data;
    received = performance.now();
    if (changed) {
      paint();
      await recent();
    } else tick();
    $('#connection-error').textContent = timer?.clock_error ? 'O horário do computador voltou no tempo. Corrija o relógio do sistema antes de continuar.' : '';
  } catch (error) {
    if (sequence === generation) $('#connection-error').textContent = error.message + ' O contador exibido é uma estimativa até reconectar.';
  }
}
$('#today-course').onchange = choices;
$('#today-subject').onchange = () => {
  $('#free-label').hidden = $('#today-subject').value !== 'free';
  operationKey = crypto.randomUUID();
};
$('#start-form').onsubmit = async e => {
  e.preventDefault();
  if (busy) return;
  const selected = $('#today-subject').value;
  if (!selected) return;
  busy = true;
  ++generation;
  $('#start-button').disabled = true;
  $('#timer-error').textContent = '';
  try {
    accept(await send('/timer', {
      subject_id: selected === 'free' ? null : Number(selected),
      title: $('#free-title').value,
      operation_key: operationKey
    }));
    operationKey = crypto.randomUUID();
  } catch (error) {
    $('#timer-error').textContent = error.message;
    busy = false;
    await refresh();
  } finally {
    busy = false;
    $('#start-button').disabled = false;
    paint();
  }
};
async function action(target, verb, values = {}) {
  if (busy) throw new Error('Aguarde o salvamento em andamento.');
  busy = true;
  ++generation;
  paint();
  $('#timer-error').textContent = '';
  try {
    const result = await send(`/timer/${target.id}/${verb}`, {
      ...values,
      version: target.version
    });
    accept(result);
    if (verb === 'finish') toast('Sessão salva. Seu estudo ficou registrado.');
    if (verb === 'cancel') toast('Relógio descartado. Nenhum tempo somado ao histórico.');
    if (verb === 'recover') toast('Período confirmado. O relógio está pausado.');
    if (verb === 'finish') await recent();
  } catch (error) {
    if (error.status === 409) error.message += ' Se este formulário estiver aberto, feche-o e abra novamente com o estado atual.';
    $('#timer-error').textContent = error.message;
    busy = false;
    await refresh();
    throw error;
  } finally {
    busy = false;
    paint();
  }
}

function recovery(target) {
  const operation_key = crypto.randomUUID();
  const canCut = target.status === 'running';
  const started = localInput(target.open_interval.started_at);
  const el = dialog('Revisar período', `<p>Estudo líquido registrado: <strong>${duration(target.effective_seconds)}</strong>. Após confirmar, o relógio ficará pausado.</p>
  <label>Como tratar o período?<select name="choice"><option value="full">Confirmar todo o tempo registrado</option>${canCut?'<option value="cutoff">Parei antes: informar horário</option>':''}</select></label>
  <div data-cutoff hidden><p class="field-help">Somente o trecho atual, iniciado em ${esc(started.replace('T',' '))}, será ajustado. O tempo depois do horário informado será uma pausa. Fuso: America/Sao_Paulo.</p><label>Quando parei de estudar<input name="cutoff_at" type="datetime-local" step="1" min="${started}" value="${localInput(target.server_now)}" disabled></label></div>`, async values => action(target, 'recover', {
    ...values,
    operation_key
  }), 'Confirmar período');
  $('[name=choice]', el).onchange = e => {
    const cut = e.target.value === 'cutoff';
    $('[data-cutoff]', el).hidden = !cut;
    const input = $('[name=cutoff_at]', el);
    input.disabled = !cut;
    input.required = cut;
  };
}
$('#timer-actions').onclick = async e => {
  const verb = e.target.closest('[data-action]')?.dataset.action;
  if (!verb || !timer) return;
  const target = {
    ...timer
  };
  if (verb === 'recover') return recovery(target);
  if (verb === 'finish') return dialog('Finalizar estudo', `<p>Tempo líquido: <strong>${duration(elapsed())}</strong>. O relógio continua no estado atual até confirmar.</p><label>O que estudei? <span class="muted">(opcional)</span><textarea name="note" maxlength="5000" placeholder="Ex.: revisão de circuitos em série"></textarea></label>`, async values => action(target, 'finish', values), 'Salvar sessão');
  if (verb === 'cancel') return dialog('Descartar este relógio?', '<p>O tempo desta sessão não entrará no histórico. Use Finalizar se quiser salvá-lo.</p>', async () => action(target, 'cancel'), 'Descartar');
  try {
    await action(target, verb);
  } catch {
    /* Erro já exibido; o estado é recarregado. */
  }
};
$('#manual-session').onclick = async () => {
  try {
    const {
      openManual
    } = await import('./manual-session.js');
    openManual(subjects, recent);
  } catch (error) {
    toast(error.message);
  }
};
$('#recent').onclick = async e => {
  const id = e.target.closest('[data-session]')?.dataset.session;
  if (!id) return;
  try {
    const s = await api(`/sessions/${id}`);
    dialog('Tempo por dia', `<p>America/Sao_Paulo · Somente esta sessão.</p>${s.daily_allocation.map(d=>`<p><strong>${esc(d.date.split('-').reverse().join('/'))}</strong> — ${duration(d.effective_seconds)} de estudo (${d.effective_seconds} s), ${duration(d.break_seconds)} de pausa (${d.break_seconds} s)</p>`).join('')}`, null);
  } catch (error) {
    toast(error.message);
  }
};
async function init() {
  if (busy) return;
  const sequence = ++generation;
  try {
    const data = await api('/today');
    if (sequence !== generation || busy) return;
    ({
      courses,
      subjects,
      timer
    } = data);
    loaded = true;
    received = performance.now();
    const selected = $('#today-course').value;
    $('#today-course').innerHTML = '<option value="">Todos os cursos</option>' + courses.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('');
    if ([...$('#today-course').options].some(o => o.value === selected)) $('#today-course').value = selected;
    choices();
    paint();
    paintRecent(data);
    $('#connection-error').textContent = timer?.clock_error ? 'O horário do computador voltou no tempo. Corrija o relógio do sistema antes de continuar.' : '';
  } catch (error) {
    if (sequence !== generation) return;
    $('#connection-error').textContent = error.message + ' O contador exibido é uma estimativa até reconectar.';
    $('#timer-status').textContent = 'Sem conexão';
  }
}
setInterval(tick, 1000);
setInterval(() => {
  if (!document.hidden) refresh();
}, 10000);
let returnTimer;

function onReturn() {
  clearTimeout(returnTimer);
  if (!document.hidden) returnTimer = setTimeout(init, 100);
}
window.addEventListener('focus', onReturn);
document.addEventListener('visibilitychange', onReturn);
init();
