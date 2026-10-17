import {activityLink} from './activity-link.js';
import {
  $,
  esc,
  api,
  toast
} from './api.js';
import {
  clock,
  date,
  timestamp
} from './study-format.js';
let projects = [], steps = [], topics = [],
  subjects = [],
  courses = [],
  current = null,
  sequence = 0;
const form = $('#analytics-filters');
const field = name => form.elements.namedItem(name);
const minutes = s => new Intl.NumberFormat('pt-BR', {
  maximumFractionDigits: 2
}).format(s / 60);

function subjectOptions(selected = '') {
  const course = field('course_id').value;
  field('subject_id').innerHTML = '<option value="">Todas as disciplinas</option>' + (!course ? '<option value="free">Estudo avulso</option>' : '') + subjects.filter(s => !course || s.course_id === Number(course)).map(s => `<option value="${s.id}">${esc(s.name)} · ${esc(s.course_name)}${s.archived_at||s.course_archived_at?' (arquivada)':''}</option>`).join('');
  field('subject_id').value = selected;
}

function topicOptions(selected = '') {
  const course = field('course_id').value,
    subject = field('subject_id').value;
  field('topic_id').innerHTML = '<option value="">Todos os tópicos</option><option value="none">Sem tópico informado</option>' + topics.filter(t => (!course || t.course_id === Number(course)) && (!subject || t.subject_id === Number(subject))).map(t => `<option value="${t.id}">${esc(t.name)} · ${esc(t.subject_name)}</option>`).join('');
  field('topic_id').value = [...field('topic_id').options].some(o => o.value === selected) ? selected : '';
}

function projectOptions(selected='') {
  // Include projects with historical sessions in a former course too; SQL filters the snapshot.
  field('project_id').innerHTML='<option value="">Todos os projetos</option>'+projects.map(p=>`<option value="${p.id}">${esc(p.name)}${p.archived_at?' (arquivado)':''}</option>`).join('');
  field('project_id').value=selected;
}
function stepOptions(selected='') {
  const project=field('project_id').value;
  field('step_id').innerHTML='<option value="">Todas as etapas</option>'+steps.filter(s=>!project||s.project_id===Number(project)).map(s=>`<option value="${s.id}">${esc(s.name)}${!project?' · '+esc(projects.find(p=>p.id===s.project_id)?.name||''):''}</option>`).join('');
  field('step_id').value=selected;
}
function activityFilters() {
  const work=field('activity').value==='project';
  document.querySelectorAll('[data-study-filter]').forEach(el=>{el.hidden=work;el.querySelector('select').disabled=work;if(work)el.querySelector('select').value='';});
  document.querySelectorAll('[data-project-filter]').forEach(el=>{el.hidden=!work;el.querySelector('select').disabled=!work;if(!work)el.querySelector('select').value='';});
  $('#breakdown').value=work?'project':field('activity').value==='study'?'subject':'activity';
}
field('activity').onchange=()=>{activityFilters();load();};
field('project_id').onchange=()=>stepOptions();

function query(page) {
  const params = new URLSearchParams(new FormData(form));
  params.set('page', page);
  params.set('page_size', $('#page-size').value);
  return params;
}

function charts(data) {
  const peak = Math.max(1, ...data.by_day.map(d => d.effective_seconds));
  $('#day-chart').innerHTML = data.by_day.map(d => `<div class="day-column" tabindex="0" aria-label="${date(d.date)}: ${clock(d.effective_seconds)} de atividade" title="${date(d.date)} · ${clock(d.effective_seconds)} (${minutes(d.effective_seconds)} min)"><span class="day-value">${minutes(d.effective_seconds)}</span><div class="day-bar" style="height:${(d.effective_seconds/peak)*160}px" aria-hidden="true"></div><span class="day-date">${d.date.slice(8)}/${d.date.slice(5,7)}</span></div>`).join('');
  const scroll = $('.day-chart-scroll');
  scroll.scrollLeft = scroll.scrollWidth;
  const grouped = data['by_' + $('#breakdown').value];
  const max = Math.max(1, ...grouped.map(d => d.effective_seconds));
  $('#subject-chart').innerHTML = grouped.length ? grouped.map(d => `<div class="subject-bar-row" tabindex="0" aria-label="${esc(d.name)}: ${clock(d.effective_seconds)}"><div class="subject-bar-label"><span>${esc(d.name)}<small>${esc([d.subject_name,d.course_name].filter(Boolean).join(' · '))}</small></span><strong title="${clock(d.effective_seconds)}">${clock(d.effective_seconds)}</strong></div><div class="subject-track"><div class="subject-fill" style="width:${d.effective_seconds/max*100}%"></div></div></div>`).join('') : '<p class="muted">Nenhum estudo neste período.</p>';
}

function render(data) {
  current = data;
  for (const key of ['today', 'week', 'month', 'period']) {
    $('#metric-' + key).textContent = clock(data.summary[key].effective_seconds);
    $('#count-' + key).textContent = `${data.summary[key].sessions} ${data.summary[key].sessions===1?'sessão':'sessões'}${key==='week'?' · segunda até hoje':key==='month'?' · dia 1 até hoje':''}`;
  }
  $('#analysis-empty').hidden = data.history.total > 0;
  $('#filter-context').textContent = `Período aplicado: ${date(data.filters.start)} a ${date(data.filters.end)} · America/Sao_Paulo · Tempos no formato horas:minutos:segundos.`;
  charts(data);
  $('#history-body').innerHTML = data.history.rows.length ? data.history.rows.map(r => {
    const partial = r.effective_seconds !== r.total_effective_seconds || r.break_seconds !== r.total_break_seconds || r.rest_seconds !== r.total_rest_seconds;
    return `<tr data-session-id="${r.id}"><td><strong>${date(r.first_day)}${r.last_day!==r.first_day?' — '+date(r.last_day):''}</strong><small>${r.started_at?esc(timestamp(r.started_at))+'<br>até '+esc(timestamp(r.ended_at)):'Duração informada, sem horários'}</small>${partial?'<small>Trecho no período filtrado</small>':''}</td><td>${r.project_id?'Projeto · ':r.subject_id?'Disciplina · ':''}${esc(r.title)}<small>${esc(r.course_name||(r.project_id?'Projeto independente':'Estudo avulso'))}</small><small class="history-topic">${esc(r.project_id?(r.step_name||'Sem etapa informada'):(r.topic_name||'Sem tópico informado'))}</small></td><td class="history-time">${clock(r.effective_seconds+r.break_seconds+r.rest_seconds)}</td><td class="history-time">${clock(r.break_seconds)}</td><td class="history-time">${clock(r.rest_seconds)}</td><td class="history-time"><strong>${clock(r.effective_seconds)}</strong></td><td>${r.source==='timer'?'Cronômetro':'Manual'}<small>${r.project_id?'Trabalho':r.session_kind==='review'?'Revisão':r.session_kind==='study'?'Estudo':'Tipo não informado'}</small>${r.correction_version>1?'<small>Corrigido · v'+r.correction_version+'</small>':''}</td><td>${esc(r.note)||'<span class="muted">—</span>'}</td><td><a class="button secondary small" href="${activityLink(r)}">${r.project_id?'Trabalhar novamente':'Estudar novamente'}</a><button class="button secondary small" data-edit="${r.id}">Corrigir</button><button class="text-button" data-audit="${r.id}">Alterações (${r.correction_version-1})</button></td></tr>`;
  }).join('') : '<tr><td colspan="9" class="muted">Nenhuma sessão corresponde aos filtros.</td></tr>';
  $('#page-info').textContent = `Página ${data.history.page} de ${data.history.pages} · ${data.history.total} sessões · total do período: ${clock(data.summary.period.effective_seconds)}`;
  $('#previous-page').disabled = data.history.page <= 1;
  $('#next-page').disabled = data.history.page >= data.history.pages;
  $('#export-csv').disabled = false;
}
async function load(page = 1) {
  const run = ++sequence,
    params = query(page);
  $('#analytics-results').setAttribute('aria-busy', 'true');
  $('#export-csv').disabled = true;
  $('#analytics-error').textContent = '';
  try {
    const data = await api('/analytics?' + params);
    if (run !== sequence) return;
    render(data);
    $('#analytics-results').hidden = false;
    field('start').value = data.filters.start;
    field('end').value = data.filters.end;
    params.set('start', data.filters.start);
    params.set('end', data.filters.end);
    params.set('page', data.history.page);
    history.replaceState(null, '', '/analytics?' + params);
  } catch (error) {
    if (run !== sequence) return;
    $('#analytics-error').textContent = error.message;
    $('#analytics-results').hidden = true;
  } finally {
    if (run === sequence) $('#analytics-results').setAttribute('aria-busy', 'false');
  }
}
form.onsubmit = e => {
  e.preventDefault();
  load();
};
field('course_id').onchange = () => {
  subjectOptions();
  topicOptions();
  projectOptions();stepOptions();
};
field('subject_id').onchange = () => topicOptions();
$('#breakdown').onchange = () => {
  if (current) charts(current);
};
$('#reset-filters').onclick = () => {
  form.reset();
  field('start').value = '';
  field('end').value = '';
  subjectOptions();
  topicOptions();
  activityFilters();projectOptions();stepOptions();
  load();
};
$('#page-size').onchange = () => load();
$('#previous-page').onclick = () => load(current.history.page - 1);
$('#next-page').onclick = () => load(current.history.page + 1);
$('#history-body').onclick = async e => {
  const edit = e.target.closest('[data-edit]')?.dataset.edit,
    audit = e.target.closest('[data-audit]')?.dataset.audit;
  if (!edit && !audit) return;
  try {
    const {
      editSession,
      showCorrections
    } = await import('./session-editor.js');
    if (edit) await editSession(edit, subjects, () => load(current.history.page));
    if (audit) await showCorrections(audit);
  } catch (error) {
    toast(error.message);
  }
};
$('#export-csv').onclick = async () => {
  if (!current) return;
  $('#export-csv').disabled = true;
  const f = current.filters,
    params = new URLSearchParams({
      start: f.start,
      end: f.end
    });
  if (f.course_id) params.set('course_id', f.course_id);
  if (f.subject_id) params.set('subject_id', f.subject_id);
  if (f.topic_id) params.set('topic_id', f.topic_id);
  for (const key of ['activity','project_id','step_id']) if(f[key])params.set(key,f[key]);
  try {
    const response = await fetch('/api/analytics/export.csv?' + params);
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || 'Falha ao exportar.');
    }
    const url = URL.createObjectURL(await response.blob());
    const a = document.createElement('a');
    a.href = url;
    a.download = `plano-estudos-${f.start}-a-${f.end}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast('CSV exportado com todos os registros dos filtros aplicados.');
  } catch (error) {
    $('#analytics-error').textContent = error.message || 'Não foi possível exportar.';
  } finally {
    $('#export-csv').disabled = false;
  }
};
async function init() {
  try {
    [courses, subjects, topics, projects, steps] = await Promise.all([api('/courses?archived=1'), api('/subjects?archived=1'), api('/topics?archived=1'),api('/projects?archived=1'),api('/project-steps')]);
    field('course_id').innerHTML = '<option value="">Todos os cursos</option>' + courses.map(c => `<option value="${c.id}">${esc(c.name)}${c.archived_at?' (arquivado)':''}</option>`).join('');
    const params = new URLSearchParams(location.search);
    for (const key of ['start', 'end', 'course_id', 'activity'])
      if (params.has(key)) field(key).value = params.get(key);
    activityFilters();
    projectOptions(params.get('project_id')||'');
    stepOptions(params.get('step_id')||'');
    subjectOptions(params.get('subject_id') || '');
    topicOptions(params.get('topic_id') || '');
    if (['20', '50', '100'].includes(params.get('page_size'))) $('#page-size').value = params.get('page_size');
    await load(params.get('page') || 1);
  } catch (error) {
    $('#analytics-error').textContent = error.message;
    $('#analytics-results').hidden = true;
  }
}
init();
