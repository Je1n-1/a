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
const selected = () => courses.find(c => c.id === selectedId);
const options = value => Object.entries(labels).map(([key, label]) => `<option value="${key}" ${key===value?'selected':''}>${label}</option>`).join('');
async function load() {
  const archived = $('#show-archived').checked ? '1' : '0';
  [courses, subjects] = await Promise.all([api('/courses?archived=' + archived), api('/subjects?archived=' + archived)]);
  if (!courses.some(c => c.id === selectedId)) selectedId = courses[0]?.id || null;
  history.replaceState(null, '', selectedId ? '/subjects?course=' + selectedId : '/subjects');
  draw();
}

function draw() {
  $('#course-count').textContent = courses.length;
  $('#courses').innerHTML = courses.map(c => `<button class="course-item ${selectedId===c.id?'active':''}" data-course="${c.id}" ${selectedId===c.id?'aria-current="true"':''}><strong>${esc(c.name)}</strong><span>${c.subject_count} disciplina(s)${c.archived_at?' · Arquivado':''}</span></button>`).join('') || '<p class="muted">Seu primeiro curso começa aqui.</p>';
  const c = selected();
  if (!c) {
    $('#catalog').innerHTML = `<div class="empty"><div class="empty-icon" aria-hidden="true">▤</div><h2>Uma biblioteca do seu jeito.</h2><p>Adicione um curso para importar sua grade ou cadastrar disciplinas.</p><button class="button primary" data-new-course>＋ Criar primeiro curso</button></div>`;
    return;
  }
  const rows = subjects.filter(s => s.course_id === c.id);
  $('#catalog').innerHTML = `<header class="catalog-header"><div><p class="eyebrow">${c.archived_at?'CURSO ARQUIVADO':'CURSO SELECIONADO'}</p><h2>${esc(c.name)}</h2><p class="muted">${esc(c.institution||'Sua jornada de aprendizado')} · ${rows.length} disciplina(s)</p></div><div class="actions"><button class="button small ghost" data-edit-course>Editar</button><button class="button small ghost" data-archive-course>${c.archived_at?'Restaurar':'Arquivar'}</button>${!c.archived_at?'<button class="button small primary" data-import>↓ Importar grade</button>':''}</div></header>${lastImport?`<p class="import-result" role="status">${esc(lastImport)}</p>`:''}<div class="catalog-toolbar"><input id="subject-search" type="search" aria-label="Pesquisar disciplina" placeholder="Buscar nome, código ou período" value="${esc(filter)}"><select id="subject-status" aria-label="Filtrar situação"><option value="">Todas as situações</option>${options(status)}</select>${!c.archived_at?'<button class="button secondary" data-new-subject>＋ Disciplina</button>':''}</div><div id="subject-results"></div>`;
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
  const q = filter.toLocaleLowerCase('pt-BR');
  const rows = subjects.filter(s => s.course_id === c.id && (!status || s.academic_status === status) && [s.name, s.code, s.period].join(' ').toLocaleLowerCase('pt-BR').includes(q));
  $('#subject-results').innerHTML = rows.length ? `<div class="table-scroll"><table class="subjects-table"><thead><tr><th>Disciplina</th><th>Situação</th><th>Carga</th><th>Ações</th></tr></thead><tbody>${rows.map(s=>`<tr><td><strong>${esc(s.name)}</strong><small>${esc([s.code,s.period].filter(Boolean).join(' · ')||'Sem código ou período')}</small></td><td><span class="badge ${esc(s.academic_status)}">${s.archived_at?'Arquivada':labels[s.academic_status]}</span></td><td>${s.workload_minutes?esc(new Intl.NumberFormat('pt-BR',{maximumFractionDigits:2}).format(s.workload_minutes/60))+' h':'—'}</td><td><div class="row-actions">${!s.archived_at&&!c.archived_at?`<button class="button small secondary" data-study="${s.id}" aria-label="Estudar ${esc(s.name)}">▶ Estudar</button><button class="icon-button" data-edit-subject="${s.id}" aria-label="Editar ${esc(s.name)}">✎</button>`:''}<button class="icon-button" data-archive-subject="${s.id}" aria-label="${s.archived_at?'Restaurar':'Arquivar'} ${esc(s.name)}">${s.archived_at?'↥':'↓'}</button></div></td></tr>`).join('')}</tbody></table></div><div class="catalog-footer">${rows.length} disciplina(s) · Carga da grade é uma referência, não tempo estudado.</div>` : `<div class="empty"><h2>${filter||status?'Nenhuma disciplina nesse filtro.':'Sua grade ainda está vazia.'}</h2><p>${filter||status?'Tente outro nome ou situação.':'Importe um arquivo ou adicione a primeira disciplina. Depois, é só apertar Estudar.'}</p>${!filter&&!status&&!c.archived_at?'<button class="button primary" data-import>↓ Importar grade curricular</button>':''}</div>`;
}

function courseEditor(c) {
  dialog(c ? 'Editar curso' : 'Novo curso', `<label>Nome do curso<input name="name" required maxlength="200" value="${esc(c?.name)}" placeholder="Ex.: Engenharia Elétrica"></label><label>Instituição <span class="muted">(opcional)</span><input name="institution" maxlength="200" value="${esc(c?.institution)}" placeholder="Onde você estuda?"></label>`, async values => {
    const saved = await send('/courses' + (c ? '/' + c.id : ''), values, c ? 'PATCH' : 'POST');
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
    await send('/subjects' + (s ? '/' + s.id : ''), {
      ...values,
      course_id: c.id,
      workload_minutes: minutes
    }, s ? 'PATCH' : 'POST');
    await load();
    toast('Disciplina salva.');
  });
}

function archive(kind, row) {
  const restoring = !!row.archived_at;
  dialog(restoring ? 'Restaurar ' + (kind === 'course' ? 'curso' : 'disciplina') : 'Arquivar ' + (kind === 'course' ? 'curso' : 'disciplina'), `<p><strong>${esc(row.name)}</strong></p><p class="muted">${restoring?'Este item voltará à sua biblioteca.':'O item sai da lista ativa. Seus estudos e sessões continuam preservados.'}</p>`, async () => {
    await send('/' + kind + '/' + row.id + '/archive', {
      archived: !restoring
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
    if (b.dataset.course) {
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
    else if (b.dataset.study) {
      b.disabled = true;
      await studyNow(Number(b.dataset.study));
      location.href = '/';
    }
  } catch (error) {
    b.disabled = false;
    toast(error.message);
  }
});
load().catch(error => {
  $('#catalog').innerHTML = `<div class="empty"><h2>Não foi possível carregar.</h2><p>${esc(error.message)}</p><button class="button" onclick="location.reload()">Tentar novamente</button></div>`;
});
