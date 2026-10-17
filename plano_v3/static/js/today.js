import {projectPicker} from './project-picker.js';
import {activityLink} from './activity-link.js';
import {enableBreakSound} from './break-alarm.js';
import {
  topicPicker
} from './topics.js';
import {
  publishTimer,
  notifySessionChange
} from './active-session.js';
import {
  $,
  esc,
  api,
  send,
  toast,
  dialog,
  duration,
  labels,
  validateTimer
} from './api.js';
import {
  clock,
  localInput
} from './study-format.js';
let subjects = [],
  reviewSubjects = new Set(),
  courses = [],
  timer = null,
  received = 0,
  busy = false,
  operationKey = crypto.randomUUID(),
  generation = 0,
  loaded = false;
const picker = topicPicker($('#start-topics'), {allowBulk: true});
const workPicker = projectPicker($('#project-choice'));
const isProject = () => $('#activity-kind').value === 'project';
function activityMode() {
  $('#study-choice').hidden = isProject();
  $('#project-choice').hidden = !isProject();
  $('#study-choice').querySelectorAll('input,select,button').forEach(x=>x.disabled=isProject());
  $('#project-choice').querySelectorAll('input,select').forEach(x=>x.disabled=!isProject());
  $('#start-button').textContent = isProject()?'▶ Iniciar trabalho':'▶ Iniciar estudo';
}
$('#activity-kind').onchange = async () => {activityMode();operationKey=crypto.randomUUID();if(isProject())await workPicker.load();else await prepareTopic();};
activityMode();
const liveSeconds = () => Math.max(0, Math.floor((performance.now() - received) / 1000));
const elapsed = () => timer ? timer.effective_seconds + (timer.status === 'running' ? liveSeconds() : 0) : 0;
const pauses = () => timer ? timer.break_seconds + (timer.status === 'paused' && !timer.rest_active ? liveSeconds() : 0) : 0;
const rests = () => timer ? (timer.rest_seconds || 0) + (timer.rest_active ? liveSeconds() : 0) : 0;
const isActive = data => data && ['running', 'paused'].includes(data.status);

function accept(data) {
  validateTimer(data);
  timer = isActive(data) ? data : null;
  received = performance.now();
  paint();
}

function tick() {
  const seconds = elapsed();
  $('#elapsed').textContent = [Math.floor(seconds / 3600), Math.floor(seconds % 3600 / 60), seconds % 60].map(n => String(n).padStart(2, '0')).join(':');
  $('#effective').textContent = duration(seconds);
  $('#breaks').textContent = duration(pauses());
  $('#rests').textContent = duration(rests());
  $('#clock-progress').style.strokeDashoffset = String(898.5 * (1 - (seconds % 3600) / 3600));
}

function paint() {
  publishTimer(timer);
  $('#timer-status').textContent = timer ? (timer.rest_active ? 'Em intervalo' : timer.status === 'paused' ? 'Em pausa curta' : timer.project_id ? 'Em trabalho' : 'Em estudo') : 'Pronto para começar';
  $('#timer-status').classList.toggle('green', timer?.status === 'running');
  $('#clock-hint').textContent = timer ? (timer.rest_active ? 'Descanso programado. Retome quando voltar.' : timer.status === 'paused' ? 'Pausa curta em andamento.' : 'Um minuto de cada vez.') : 'Seu próximo passo começa aqui.';
  $('#active-title').innerHTML = timer ? `<strong>${timer.project_id?'Projeto · ':''}${esc(timer.title)}</strong>${(timer.topic_name||timer.step_name)?`<span class="active-topic">${esc(timer.topic_name||timer.step_name)} · ${timer.project_id?'Trabalho':timer.project_id?'Trabalho':r.session_kind==='review'?'Revisão':'Estudo'}</span>`:''}<small>${esc(timer.course_name||(timer.project_id?'Projeto independente':'Estudo avulso'))}</small>` : '';
  $('#selection-card').hidden = !!timer;
  const needsReview = timer?.recovery_required;
  $('#recovery-notice').hidden = !needsReview;
  $('#recovery-notice').textContent = needsReview ? 'Esta sessão está aberta há 8 horas ou mais desde a última confirmação. Revise o período antes de retomar ou finalizar.' : '';
  $('#timer-actions').innerHTML = timer ? `
  <button class="button secondary" data-action="${timer.status==='paused'?'resume':'pause'}" ${needsReview&&timer.status==='paused'?'disabled':''}>${timer.status==='paused'?'▶ Retomar':'Ⅱ Pausa curta'}</button>
  ${timer.rest_active?'<button class="button ghost" data-action="pause">Trocar para pausa curta</button>':''}
  <button class="button secondary" data-action="break-plan" ${needsReview?'disabled':''}>${timer.break_until?'Alterar intervalo':'Intervalo de estudo'}</button>
  <button class="button primary" data-action="${needsReview?'recover':'finish'}">${needsReview?'Revisar período':'✓ Finalizar'}</button>
  ${needsReview?'':'<button class="button ghost" data-action="recover">Revisar período</button>'}
  <button class="button ghost" data-action="cancel">Descartar</button>` : '<span class="muted">Escolha seu foco para iniciar.</span>';
  if (busy) $('#timer-actions').querySelectorAll('button').forEach(b => b.disabled = true);
  tick();
}

function choices() {
  const course = $('#today-course').value,
    previous = $('#today-subject').value;
  const q = $('#today-search').value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const rows = subjects.filter(s => (!course || s.course_id === Number(course)) && (s.name + ' ' + s.course_name).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().includes(q));
  const groups = [
    {label: 'Em andamento', rows: []},
    {label: 'Para revisar', rows: []},
    {label: 'Concluídas', rows: []},
    {label: 'Outras disciplinas', rows: []}
  ];
  for (const s of rows) {
    const group = s.academic_status === 'in_progress' ? 0 : reviewSubjects.has(s.id) ? 1 : s.academic_status === 'completed' ? 2 : 3;
    groups[group].rows.push(s);
  }
  for (const group of groups) group.rows.sort((a,b) => a.name.localeCompare(b.name, 'pt-BR') || a.course_name.localeCompare(b.course_name, 'pt-BR') || a.id-b.id);
  $('#today-subject').innerHTML = '<option value="">Selecione uma disciplina</option>' + groups.filter(g => g.rows.length).map(g => `<optgroup label="${g.label} (${g.rows.length})">${g.rows.map(s => `<option value="${s.id}">${esc(s.name)}${!course?' · '+esc(s.course_name):''}${g.label==='Outras disciplinas'?' · '+esc(labels[s.academic_status]):''}${reviewSubjects.has(s.id)?(s.academic_status==='completed'?' · Concluída, revisão pendente':' · Revisão pendente'):''}</option>`).join('')}</optgroup>`).join('') + '<option value="free">Estudo avulso</option>';
  if ([...$('#today-subject').options].some(o => o.value === previous)) $('#today-subject').value = previous;
  const suggestion = groups.find(g => g.rows.length);
  const best = suggestion?.rows[0];
  $('#subject-suggestion').hidden = !best || !!$('#today-subject').value;
  $('#subject-suggestion').innerHTML = best ? `<span class="eyebrow">SUGESTÃO · ${esc(suggestion.label)}</span><button type="button" class="button secondary full" data-suggest="${best.id}">${esc(best.name)}${!course?`<small>${esc(best.course_name)}</small>`:''}</button><small>Selecionar prepara o estudo. O relógio só começa ao clicar em Iniciar estudo.</small>` : '';
  $('#subject-choice-help').textContent = rows.length ? 'Prioridade: em andamento → revisão pendente → concluídas. As demais ficam em Outras disciplinas.' : 'Nenhuma disciplina corresponde à busca. Altere os filtros ou escolha Estudo avulso.';
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
  $('#recent').innerHTML = rows.length ? rows.map(r => `<article class="recent-item"><div><strong>${r.project_id?'Projeto · ':''}${esc(r.title)}</strong><small>${esc(r.course_name||(r.project_id?'Projeto independente':'Estudo avulso'))} · ${esc(dateLabel(r))} · ${r.source==='manual'?(r.started_at?'Horários informados manualmente':'Duração informada manualmente'):'Cronômetro'}</small>${(r.topic_name||r.step_name)?`<p><strong>${esc(r.topic_name||r.step_name)}</strong> · ${r.project_id?'Trabalho':r.session_kind==='review'?'Revisão':'Estudo'}</p>`:''}${r.note?`<p>${esc(r.note)}</p>`:''}<a class="inline-link repeat-study" href="${activityLink(r)}">${r.project_id?'Trabalhar novamente':'Estudar novamente'}</a> <button class="inline-link" data-session="${r.id}">Ver divisão por dia</button></div><div class="recent-time">${duration(r.effective_seconds)}<small>${duration(r.break_seconds)} de pausa curta</small><small>${duration(r.rest_seconds)} de intervalo</small></div></article>`).join('') : '<div class="empty"><h3>Sua primeira sessão começa hoje.</h3><p>Ao finalizar o relógio, o tempo e suas anotações aparecem aqui.</p></div>';
}
async function recent() {
  paintRecent(await api('/today?catalog=0'));
}
async function refresh() {
  if (!loaded) return init();
  if (busy) return;
  const sequence = ++generation;
  try {
    const data = validateTimer(await api('/timer'), true);
    if (sequence !== generation || busy) return;
    const changed = timer?.id !== data?.id || timer?.version !== data?.version || timer?.recovery_required !== data?.recovery_required;
    timer = data;
    received = performance.now();
    if (changed) {
      paint();
      await recent();
    } else {
      tick();
      publishTimer(timer);
    }
    $('#connection-error').textContent = timer?.clock_error ? 'O horário do computador voltou no tempo. Corrija o relógio do sistema antes de continuar.' : '';
  } catch (error) {
    if (sequence === generation) $('#connection-error').textContent = error.message + ' O contador exibido é uma estimativa até reconectar.';
  }
}
$('#today-course').onchange = () => {
  choices();
  prepareTopic();
};
$('#today-search').oninput = () => {
  const old = $('#today-subject').value;
  choices();
  if (old !== $('#today-subject').value) prepareTopic();
};

function prepareTopic() {
  return picker.load($('#today-subject').value === 'free' ? null : $('#today-subject').value);
}
$('#today-subject').onchange = () => {
  $('#subject-suggestion').hidden = !!$('#today-subject').value;
  $('#free-label').hidden = $('#today-subject').value !== 'free';
  operationKey = crypto.randomUUID();
  prepareTopic();
};
$('#subject-suggestion').onclick = e => {
  const id = e.target.closest('[data-suggest]')?.dataset.suggest;
  if (!id) return;
  $('#today-subject').value = id;
  $('#today-subject').dispatchEvent(new Event('change'));
};
$('#start-form').onsubmit = async e => {
  e.preventDefault();
  if (busy) return;
  const selected = $('#today-subject').value;
  if (!isProject() && !selected) return;
  busy = true;
  ++generation;
  $('#start-button').disabled = true;
  $('#timer-error').textContent = '';
  try {
    accept(await send('/timer', {
      ...(isProject()?workPicker.values():picker.values()),
      subject_id: isProject() ? null : selected === 'free' ? null : Number(selected),
      title: $('#free-title').value,
      operation_key: operationKey
    }));
    operationKey = crypto.randomUUID();
    notifySessionChange();
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
    notifySessionChange();
    if (verb === 'finish') toast('Sessão salva. Seu tempo ficou registrado.');
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
  if (verb === 'break-plan') {
    enableBreakSound();
    const el=dialog('Intervalo de estudo', `<p>O tempo será contado como intervalo programado, separado das pausas curtas. O intervalo termina ao clicar em Retomar, mesmo se o alarme já tiver tocado.</p><label>Programar por<select name="mode"><option value="duration">Duração</option><option value="return">Horário de retorno</option></select></label><label data-duration>Duração em minutos<input name="minutes" type="number" min="1" max="1440" step="1" value="60" required></label><label data-return hidden>Voltar em (São Paulo)<input name="return_at" type="datetime-local" step="1" value="${localInput(target.break_until||new Date(Date.parse(target.server_now)+3600000).toISOString())}" disabled></label><p class="field-help">Deixe uma aba do site aberta e o computador ligado para o alarme tocar. Ao reabrir, o prazo salvo será recuperado.</p><button type="button" class="button secondary" data-test-sound>Testar som</button>`, async values=>{
      await enableBreakSound();
      await action(target,'break-plan',values.mode==='duration'?{minutes:Number(values.minutes)}:{return_at:values.return_at});
    }, target.status==='running'?'Iniciar intervalo':'Programar retorno');
    $('[data-test-sound]',el).onclick=async e=>{e.target.textContent=await enableBreakSound(true)?'Som ativado':'Não foi possível ativar o som';};
    $('[name=mode]',el).onchange=e=>{
      const byDuration=e.target.value==='duration';
      $('[data-duration]',el).hidden=!byDuration;$('[data-return]',el).hidden=byDuration;
      $('[name=minutes]',el).disabled=!byDuration;$('[name=minutes]',el).required=byDuration;
      $('[name=return_at]',el).disabled=byDuration;$('[name=return_at]',el).required=!byDuration;
    };
    return;
  }
  if (verb === 'finish') {
    let topic = null;
    try {
      if (target.topic_id) topic = (await api('/topics?archived=1&subject_id=' + target.subject_id)).find(t => t.id === target.topic_id);
    } catch (error) {
      toast(error.message);
      return;
    }
    return dialog(target.project_id?'Finalizar trabalho':'Finalizar estudo', `<p>Tempo líquido: <strong>${duration(elapsed())}</strong>. O relógio continua no estado atual até confirmar.</p>${topic ? `<p><strong>Tópico: ${esc(target.topic_name)}</strong></p><div class="dialog-grid"><label>Conclusão<select name="completed"><option value="">Manter: ${topic.completed?'concluído':'não concluído'}</option><option value="true">Marcar como concluído</option><option value="false">Marcar como não concluído</option></select></label><label>Revisão<select name="needs_review"><option value="">Manter: ${topic.needs_review?'necessária':'não pendente'}</option><option value="true">Precisa de revisão</option><option value="false">Revisão realizada / sem pendência</option></select></label></div>` : ''}<label>O que fiz nesta sessão <span class="muted">(opcional)</span><textarea name="note" maxlength="5000" placeholder="Ex.: exercícios feitos e dúvidas que ficaram"></textarea></label>`, async values => {
      const result = {};
      for (const field of ['completed', 'needs_review'])
        if (values[field]) result[field] = values[field] === 'true';
      await action(target, 'finish', {
        note: values.note,
        ...(Object.keys(result).length ? {
          topic_result: {
            version: topic.version,
            ...result
          }
        } : {})
      });
    }, 'Salvar sessão');
  }
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
    dialog('Tempo por dia', `<p>America/Sao_Paulo · Somente esta sessão.</p>${s.daily_allocation.map(d=>`<p><strong>${esc(d.date.split('-').reverse().join('/'))}</strong> — ${duration(d.effective_seconds)} de estudo (${d.effective_seconds} s), ${duration(d.break_seconds)} de pausa curta (${d.break_seconds} s), ${duration(d.rest_seconds)} de intervalo (${d.rest_seconds} s)</p>`).join('')}`, null);
  } catch (error) {
    toast(error.message);
  }
};
async function init() {
  if (busy) return;
  const sequence = ++generation;
  try {
    const data = await api('/today');
    validateTimer(data.timer, true);
    if (sequence !== generation || busy) return;
    ({
      courses,
      subjects,
      timer
    } = data);
    reviewSubjects = new Set(data.review_subject_ids || []);
    loaded = true;
    received = performance.now();
    const selected = $('#today-course').value;
    $('#today-course').innerHTML = '<option value="">Todos os cursos</option>' + courses.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('');
    if ([...$('#today-course').options].some(o => o.value === selected)) $('#today-course').value = selected;
    choices();
    if (!init.prepared) {
      const params = new URLSearchParams(location.search);
      const wanted = params.get('subject');
      if(params.get('project')) {
        $('#activity-kind').value='project';activityMode();
        await workPicker.load(params.get('project'),params.get('step'));
      }
      if (wanted && [...$('#today-subject').options].some(o => o.value === wanted)) {
        $('#today-subject').value = wanted;
        $('#subject-suggestion').hidden = true;
        $('#free-title').value = params.get('title') || '';
        $('#free-label').hidden = wanted !== 'free';
      }
      await picker.load(wanted && wanted !== 'free' ? wanted : null, params.get('topic'), params.get('kind') === 'review' ? 'review' : 'study');
      init.prepared = true;
    }
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
window.addEventListener('session-refresh', onReturn);
window.addEventListener('timer-state-changed',event=>{
  if (!busy) {++generation;accept(event.detail);}
});
document.addEventListener('visibilitychange', onReturn);
init();
