import {moduleGroups, textKey} from './module-groups.js';
import {icon} from './icons.js';
import {
  $,
  esc,
  api,
  send,
  toast,
  dialog,
  labels,
  studyNow
} from './api.js';
let courses = [],
  subjects = [],
  selectedId = Number(new URLSearchParams(location.search).get('course')) || null;
let filter = '',
  status = '',
  lastImport = '';
const linkedTarget = new URLSearchParams(location.search);
if (linkedTarget.get('archived') === '1') $('#show-archived').checked = true;
const selected = () => courses.find(c => c.id === selectedId);
const options = value => Object.entries(labels).map(([key, label]) => `<option value="${key}" ${key===value?'selected':''}>${label}</option>`).join('');
function showSubject(subject) {
  if (!subject) return;
  const params = new URLSearchParams(location.search);
  params.set('course', subject.course_id); params.set('subject', subject.id);
  history.pushState(null, '', '/subjects?' + params);
  $('#subject-results').hidden = true;
  $('#catalog').querySelector('.catalog-toolbar').hidden = true;
  const detail = $('#subject-detail'); detail.hidden = false;
  detail.innerHTML = `<div class="subject-detail-head"><button class="button ghost small" data-subject-back>← Voltar à grade</button><span class="eyebrow">DETALHE DA DISCIPLINA</span><h2>${esc(subject.name)}</h2><p class="muted">${esc(selected()?.name||'')} · ${esc(subject.period||'Período não informado')}</p></div><div class="subject-detail-facts"><div><small>SITUAÇÃO</small><strong>${esc(labels[subject.academic_status]||'Não informada')}</strong></div><div><small>CARGA DA GRADE</small><strong>${subject.workload_minutes?esc(new Intl.NumberFormat('pt-BR',{maximumFractionDigits:2}).format(subject.workload_minutes/60))+' h':'Não informada'}</strong></div><div><small>CÓDIGO</small><strong>${esc(subject.code||'—')}</strong></div></div>${subject.notes?`<p class="subject-detail-notes">${esc(subject.notes)}</p>`:''}<div class="actions"><a class="button primary" href="/?subject=${subject.id}">Estudar</a><button class="button secondary" data-topics="${subject.id}">Abrir tópicos</button><button class="button secondary" data-study-route="${subject.id}">Roteiro de estudos</button><button class="button ghost" data-edit-subject="${subject.id}">Editar</button><button class="button ghost" data-archive-subject="${subject.id}">Arquivar</button></div>`;
}
async function load() {
  const archived = $('#show-archived').checked ? '1' : '0';
  [courses, subjects] = await Promise.all([api('/courses?archived=' + archived), api('/subjects?archived=' + archived)]);
  if (!courses.some(c => c.id === selectedId)) selectedId = courses[0]?.id || null;
  const locationParams = new URLSearchParams();
  if (selectedId) locationParams.set('course', selectedId);
  const requestedSubject = Number(new URLSearchParams(location.search).get('subject'));
  if (requestedSubject && subjects.some(s=>s.id===requestedSubject && s.course_id===selectedId)) locationParams.set('subject', requestedSubject);
  history.replaceState(null, '', '/subjects' + (locationParams.size?'?'+locationParams:''));
  draw();
}

function draw() {
  $('#course-count').textContent = courses.length;
  $('#courses').innerHTML = courses.map(c => `<button class="course-item ${selectedId===c.id?'active':''}" data-course="${c.id}" ${selectedId===c.id?'aria-current="true"':''}><strong>${esc(c.name)}</strong><span>${c.subject_count} disciplina(s)${c.archived_at?' · Arquivado':''}</span></button>`).join('') || '<p class="muted">Seu primeiro curso começa aqui.</p>';
  const c = selected();
  if (!c) {
    $('#subject-metrics').innerHTML = '';
    $('#catalog').innerHTML = `<div class="empty"><div class="empty-icon" aria-hidden="true">▤</div><h2>Uma biblioteca do seu jeito.</h2><p>Adicione um curso para importar sua grade ou cadastrar disciplinas.</p><button class="button primary" data-new-course>＋ Criar primeiro curso</button></div>`;
    return;
  }
  const rows = subjects.filter(s => s.course_id === c.id);
  $('#catalog').innerHTML = `<header class="catalog-header"><div><p class="eyebrow">${c.archived_at?'CURSO ARQUIVADO':'CURSO SELECIONADO'}</p><h2>${esc(c.name)}</h2><p class="muted">${esc(c.institution||'Sua jornada de aprendizado')} · ${rows.length} disciplina(s)</p></div><div class="actions"><button class="button small ghost" data-edit-course>Editar</button><button class="button small ghost" data-archive-course>${c.archived_at?'Restaurar':'Arquivar'}</button>${!c.archived_at?`<button class="button small primary" data-import>${icon('download')} Importar grade</button>`:''}</div></header>${lastImport?`<p class="import-result" role="status">${esc(lastImport)}</p>`:''}<div class="catalog-toolbar"><input id="subject-search" type="search" aria-label="Pesquisar disciplina" placeholder="Buscar nome, código ou período" value="${esc(filter)}"><select id="subject-status" aria-label="Filtrar situação"><option value="">Todas as situações</option>${options(status)}</select>${!c.archived_at?`<button class="button secondary" data-review-topics>Tópicos para revisão</button><button class="button secondary" data-new-subject>${icon('plus')} Disciplina</button>`:''}</div><div id="subject-results"></div><section id="subject-detail" class="subject-detail card" hidden></section>`;
  const requestedSubject = Number(new URLSearchParams(location.search).get('subject'));
  if (requestedSubject) { const subject = subjects.find(s=>s.id===requestedSubject && s.course_id===c.id); if (subject) { showSubject(subject); return; } }
  $('#subject-status').value = status;
  drawRows();
  $('#subject-search').oninput = e => {
    filter = e.target.value;
    drawRows();
  };
  $('#subject-status').onchange = e => {
    status = e.target.value;
    drawRows();
  };
}

function drawRows() {
  const c = selected();
  const q = textKey(filter);
  const all = subjects.filter(s=>s.course_id===c.id).sort((a,b)=>a.id-b.id);
  const rows = all.filter(s=>(!status||s.academic_status===status)&&textKey([s.name,s.code,s.period].join(' ')).includes(q));
  const finished=s=>['completed','exempted'].includes(s.academic_status);
  const done=all.filter(finished).length;
  $('#subject-metrics').innerHTML = [
    ['book',all.length,'Disciplinas no curso'],
    ['target',all.length?Math.round(done/all.length*100)+'%':'0%','Progresso acadêmico'],
    ['check',done,'Concluídas ou dispensadas'],
    ['layers',all.filter(s=>s.academic_status==='in_progress').length,'Em andamento']
  ].map(([symbol,value,label])=>`<article class="metric-card">${icon(symbol)}<div><strong>${value}</strong><span>${label}</span></div></article>`).join('');
  const groups=moduleGroups(rows);
  const cards=groups.map((g,i)=>{
    const n=g.rows.filter(finished).length;
    return `<a class="module-card" href="#module-${i}"><strong>${esc(g.name)}</strong><progress max="${g.rows.length}" value="${n}" aria-label="${esc(g.name)}: ${n} de ${g.rows.length} concluídas ou dispensadas"></progress><small>${n}/${g.rows.length} concluídas ou dispensadas</small></a>`;
  }).join('');
  const row=s=>`<tr><td><button class="subject-name-link" data-open-subject="${s.id}">${esc(s.name)}</button><small>${esc([s.code,s.period].filter(Boolean).join(' · ')||'Sem código ou período')}</small>${s.notes?`<details class="subject-notes"><summary>Observações e origem</summary><p>${esc(s.notes)}</p></details>`:''}</td><td data-label="Situação">${s.archived_at||c.archived_at?`<span class="badge">${s.archived_at?'Arquivada':labels[s.academic_status]}</span>`:`<span class="badge ${s.academic_status}">${labels[s.academic_status]}</span>`}</td><td data-label="Carga curricular">${s.workload_minutes?esc(new Intl.NumberFormat('pt-BR',{maximumFractionDigits:2}).format(s.workload_minutes/60))+' h':'—'}</td><td><details class="row-action-menu"><summary>Ações</summary><div class="row-actions">${!s.archived_at&&!c.archived_at?`<button class="button small secondary" data-study="${s.id}" aria-label="Estudar ${esc(s.name)}">${icon("play")} Estudar</button><button class="button small ghost" data-topics="${s.id}">Tópicos</button><button class="button small ghost" data-study-route="${s.id}">Roteiro</button><button class="button small ghost" data-edit-subject="${s.id}">Editar</button>`:''}<button class="button small ghost" data-archive-subject="${s.id}">${s.archived_at?'Restaurar':'Arquivar'}</button></div></details></td></tr>`;
  $('#subject-results').innerHTML = rows.length ? `
    <section class="course-progress"><div><strong>Progresso acadêmico</strong><span>${done}/${all.length} concluídas ou dispensadas · ${Math.round(done/all.length*100)}%</span></div><progress max="${all.length}" value="${done}" aria-label="Progresso acadêmico"></progress></section>

    <details class="module-navigation"><summary>Ir para um bloco da grade · ${groups.length} ${groups.length===1?'bloco':'blocos'}${filter||status?' neste filtro':''}</summary><div class="module-grid">${cards}</div></details>
    ${groups.map((g,i)=>`<section class="subject-module" id="module-${i}"><header><h3>${esc(g.name)}</h3><span>${g.rows.length} componente(s) · ${new Intl.NumberFormat('pt-BR').format(g.rows.reduce((n,r)=>n+(r.workload_minutes||0),0)/60)} h de carga</span></header><div class="table-scroll"><table class="subjects-table"><thead><tr><th>Disciplina</th><th>Situação</th><th>Carga</th><th>Ações</th></tr></thead><tbody>${g.rows.map(row).join('')}</tbody></table></div></section>`).join('')}
    <div class="catalog-footer">${rows.length} disciplina(s) · Carga da grade é uma referência, não tempo estudado.</div>` : `<div class="empty"><h2>${filter||status?'Nenhuma disciplina nesse filtro.':'Sua grade ainda está vazia.'}</h2><p>${filter||status?'Tente outro nome ou situação.':'Importe um PDF ou adicione a primeira disciplina. A prévia organiza os módulos antes de salvar.'}</p>${!filter&&!status&&!c.archived_at?`<button class="button primary" data-import>${icon('download')} Importar grade curricular</button>`:''}</div>`;
}

async function saveCatalog(path, values, method = 'POST') {
  try { return await send(path, values, method); }
  catch (error) {
    if (error.status === 409) {
      try { await load(); } catch { /* Preserve the conflict message and unsaved form. */ }
    }
    throw error;
  }
}

function courseEditor(c) {
  dialog(c ? 'Editar curso' : 'Novo curso', `<label>Nome do curso<input name="name" required maxlength="200" value="${esc(c?.name)}" placeholder="Ex.: Engenharia Elétrica"></label><label>Instituição <span class="muted">(opcional)</span><input name="institution" maxlength="200" value="${esc(c?.institution)}" placeholder="Onde você estuda?"></label>`, async values => {
    const saved = await saveCatalog('/courses' + (c ? '/' + c.id : ''), {...values, ...(c?{version:c.version}:{})}, c ? 'PATCH' : 'POST');
    selectedId = saved.id;
    await load();
    toast(c ? 'Curso atualizado.' : 'Curso criado. Agora você pode importar a grade.');
  });
}

function subjectEditor(s) {
  const c = selected();
  dialog(s ? 'Editar disciplina' : 'Nova disciplina', `<div class="dialog-grid"><label class="wide">Nome<input name="name" required maxlength="200" value="${esc(s?.name)}"></label><label>Código<input name="code" maxlength="80" value="${esc(s?.code)}"></label><label>Período / módulo<input name="period" maxlength="100" value="${esc(s?.period)}"></label><label>Carga da grade (horas)<input name="hours" type="number" min="0.016666" max="10000" step="any" value="${s?.workload_minutes?s.workload_minutes/60:''}"></label><label>Situação<select name="academic_status">${options(s?.academic_status||'not_available')}</select></label><label class="wide">Observações <span class="muted">(opcional)</span><textarea name="notes" maxlength="5000">${esc(s?.notes)}</textarea></label></div>`, async values => {
    const minutes = values.hours === '' ? null : Math.round(Number(values.hours) * 60);
    if (minutes !== null && (!Number.isFinite(minutes) || minutes <= 0)) throw new Error('Informe uma carga positiva.');
    delete values.hours;
    await saveCatalog('/subjects' + (s ? '/' + s.id : ''), {
      ...values,
      course_id: c.id,
      ...(s?{version:s.version}:{}),
      workload_minutes: minutes
    }, s ? 'PATCH' : 'POST');
    await load();
    toast('Disciplina salva.');
  });
}

function archive(kind, row) {
  const restoring = !!row.archived_at;
  dialog(restoring ? 'Restaurar ' + (kind === 'course' ? 'curso' : 'disciplina') : 'Arquivar ' + (kind === 'course' ? 'curso' : 'disciplina'), `<p><strong>${esc(row.name)}</strong></p><p class="muted">${restoring?'Este item voltará à sua biblioteca.':'O item sai da lista ativa. Seus estudos e sessões continuam preservados.'}</p>`, async () => {
    await saveCatalog('/' + kind + '/' + row.id + '/archive', {
      archived: !restoring,
      version: row.version
    });
    await load();
    toast(restoring ? 'Item restaurado.' : 'Item arquivado.');
  }, restoring ? 'Restaurar' : 'Arquivar');
}
$('#new-course').onclick = () => courseEditor();
$('#show-archived').onchange = () => load().catch(e => toast(e.message));
document.addEventListener('click', async e => {
  const b = e.target.closest('button');
  if (!b) return;
  try {
    if (b.dataset.openSubject) showSubject(subjects.find(s=>s.id===Number(b.dataset.openSubject)));
    else if (b.hasAttribute('data-subject-back')) { const p=new URLSearchParams(location.search); p.delete('subject'); history.pushState(null,'','/subjects?'+p); $('#subject-detail').hidden=true; $('#subject-results').hidden=false; $('#catalog').querySelector('.catalog-toolbar').hidden=false; }
    else if (b.dataset.course) {
      selectedId = Number(b.dataset.course);
      lastImport = '';
      filter = '';
      status = '';
      await load();
    } else if (b.hasAttribute('data-new-course')) courseEditor();
    else if (b.hasAttribute('data-edit-course')) courseEditor(selected());
    else if (b.hasAttribute('data-new-subject')) subjectEditor();
    else if (b.dataset.editSubject) subjectEditor(subjects.find(s => s.id === Number(b.dataset.editSubject)));
    else if (b.hasAttribute('data-archive-course')) archive('course', selected());
    else if (b.dataset.archiveSubject) archive('subject', subjects.find(s => s.id === Number(b.dataset.archiveSubject)));
    else if (b.hasAttribute('data-import'))(await import('./curriculum-import.js')).openImport(selected(), async summary => {
      lastImport = `Importação concluída: ${summary.inserted} inserida(s), ${summary.updated} atualizada(s), ${summary.ignored} ignorada(s).`;
      await load();
      toast(lastImport);
    });
    else if (b.dataset.topics) await (await import('./topics.js')).openTopics(subjects.find(s => s.id === Number(b.dataset.topics)));
    else if (b.dataset.studyRoute) await (await import('./study-routes.js')).openStudyRoute(Number(b.dataset.studyRoute), async () => { if (new URLSearchParams(location.search).has('subject')) showSubject(subjects.find(s=>s.id===Number(b.dataset.studyRoute))); });
    else if (b.hasAttribute('data-review-topics')) await (await import('./topics.js')).openTopics(null, selectedId);
    else if (b.dataset.study) {
      b.disabled = true;
      await studyNow(Number(b.dataset.study));

    }
  } catch (error) {
    b.disabled = false;
    toast(error.message);
  }
});
document.addEventListener('change', async e => {
  const input = e.target.closest('[data-status-id]');
  if (!input) return;
  const subject = subjects.find(s => s.id === Number(input.dataset.statusId));
  const previous = subject.academic_status;
  input.disabled = true;
  try {
    const saved = await saveCatalog('/subjects/' + subject.id, {
      academic_status: input.value,
      version: subject.version
    }, 'PATCH');
    if (saved.id !== subject.id || !labels[saved.academic_status]) throw new Error('Resposta inesperada ao salvar. Atualize a lista para conferir.');
    Object.assign(subject, saved);
    drawRows();
    toast('Situação salva: ' + labels[saved.academic_status] + '.');
  } catch (error) {
    input.value = previous;
    toast(error.message);
  } finally {
    input.disabled = false;
  }
});
load().then(async () => {
  const id = Number(linkedTarget.get('subject'));
  if (!id) return;
  const subject = subjects.find(s => s.id === id);
  if (!subject) return;
  const row = document.querySelector(`[data-status-id="${id}"], [data-archive-subject="${id}"]`)?.closest('tr');
  row?.scrollIntoView({block:'center'});
  if (row) { row.style.outline = '2px solid var(--accent)'; row.tabIndex = -1; row.focus({preventScroll:true}); }
  if (linkedTarget.has('topic')) {
    if (subject.archived_at || subject.course_archived_at) {
      const rows = await api('/topics?archived=1&subject_id='+subject.id);
      const topic = rows.find(t => t.id === Number(linkedTarget.get('topic')));
      if (topic) dialog('Conteúdo arquivado · '+subject.name, `<h3>${esc(topic.name)}</h3><p>${topic.completed?'Concluído':'Não concluído'}${topic.needs_review?' · Revisão pendente':''}</p><p class="muted">Restaure o curso ou a disciplina para voltar a estudar este conteúdo.</p>`, null);
      return;
    }
    await (await import('./topics.js')).openTopics(subject);
    const target = document.querySelector(`[data-topic-id="${Number(linkedTarget.get('topic'))}"]`);
    target?.scrollIntoView({block:'center'});
    target?.focus({preventScroll:true});
  }
}).catch(error => {
  $('#catalog').innerHTML = `<div class="empty"><h2>Não foi possível carregar.</h2><p>${esc(error.message)}</p><button class="button" data-retry>Tentar novamente</button></div>`;
  $('[data-retry]').onclick = () => location.reload();
});
