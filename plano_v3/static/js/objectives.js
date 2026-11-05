import {$, esc, api, send, duration, dialog, toast} from './api.js';
import {ObjectiveEditor} from './objective-editor.js';

document.body.classList.add('objectives-page');
const root = $('#objectives-app');
const labels = {not_started:'Não iniciado', in_progress:'Em andamento', completed:'Concluído'};
const kinds = {subject:'Disciplina', topic:'Conteúdo', project:'Projeto', step:'Etapa de projeto'};
let current = null, objectives = [], busy = false, stageFilter = '', stateFilter = '', requestSequence = 0;
const tasks = () => current?.stages.flatMap(s => s.tasks) || [];
const progress = value => `<progress class="objective-progress" max="100" value="${value}" aria-label="${value}% concluído">${value}%</progress>`;
const hours = value => value ? duration(value) : '0 h';
const badge = t => `<span class="objective-status ${t.status}">${labels[t.status]}</span>`;
const sourceLabel = s => `${kinds[s.kind]}: ${s.name}${s.parent ? ' · '+s.parent : ''}`;
const sourceLink = s => s.url ? `<a href="${esc(s.url)}">↗ ${esc(sourceLabel(s))}</a>` : esc(sourceLabel(s));

function fail(error) {
  $('#objectives-error').textContent = error.message || String(error);
  $('#objectives-error').scrollIntoView({block:'nearest'});
}
function show(view, scroll = true) {
  for (const name of ['overview','detail','create']) $('#objective'+(name==='overview'?'s-overview':'-'+name)).hidden = name !== view;
  $('#objectives-error').textContent = '';
  if (scroll) window.scrollTo({top:0});
}
function navigate(view, id = current?.id, replace = false) {
  const params = new URLSearchParams();
  if (id) params.set('objective', id);
  if (view !== 'overview') params.set('view', view);
  if ($('#objectives-archived').checked) params.set('archived', '1');
  history[replace ? 'replaceState' : 'pushState'](null, '', '/objectives'+(params.size?'?'+params:''));
  show(view);
}
function renderCards() {
  $('#objective-count').textContent = objectives.length;
  $('#objective-cards').innerHTML = objectives.map(o => `<button class="objective-card" data-select="${o.id}" aria-pressed="${current?.id===o.id}"><strong>${esc(o.title)}</strong><small>${o.progress}% concluído</small>${progress(o.progress)}</button>`).join('') || '<p class="muted">'+($('#objectives-archived').checked?'Nenhum objetivo arquivado.':'Seus caminhos aparecerão aqui.')+'</p>';
}
function nextTask(o) {
  const task = o.next_task;
  if (!task) return `<strong class="objective-next">${o.blocked_count?'Confira os pré-requisitos':'Caminho concluído'}</strong>`;
  const stage = o.stages.find(s => s.id === task.stage_id);
  return `<button class="objective-next" data-action="jump" data-task-id="${task.id}">${esc(task.title)}</button><span class="objective-next-note">${task.needs_review?'Revisão pendente':`Etapa ${(stage?.position||0)+1} · ${esc(stage?.title||'')}`}</span>`;
}
function timeExplanation() {
  return '<details class="objective-explanation"><summary>Como o progresso e as horas são calculados</summary><p>O percentual considera afazeres concluídos. A revisão é uma marca separada. Itens vinculados acompanham o estado na disciplina ou no projeto.</p><p>As horas vêm das sessões finalizadas dos vínculos atuais, inclusive anteriores ao objetivo. Uma mesma sessão entra uma vez no total do objetivo. Totais de itens ou etapas com vínculos sobrepostos não devem ser somados. Afazeres independentes ainda não recebem tempo; nenhum registro adicional é criado nas Análises.</p></details>';
}
function renderSelected() {
  const panel = $('#objective-selected'), o = current;
  if (!o) {
    panel.innerHTML = `<div class="objective-empty"><span class="empty-symbol" aria-hidden="true">◎</span><p class="eyebrow">SEU PRÓXIMO PASSO</p><h2>O que você quer ser capaz de fazer?</h2><p>Transforme essa intenção em etapas e afazeres. Aproveite seus estudos atuais ou crie um caminho independente.</p><button class="button primary" data-action="new">＋ Criar meu primeiro objetivo</button><span class="small-note muted">Você conversa com a IA que preferir e importa a proposta aqui.</span></div>`;
    return;
  }
  const activity = tasks().filter(t => t.status !== 'not_started' || t.needs_review).slice(0,3);
  panel.innerHTML = `<p class="eyebrow">OBJETIVO SELECIONADO</p><h2 class="objective-selected-title">${esc(o.title)}</h2><p class="muted">${esc(o.description)}</p>
    <div class="objective-progress-large"><p class="eyebrow">PROGRESSO DO OBJETIVO</p><div><strong>${o.progress}%</strong>${progress(o.progress)}</div></div>
    <div class="objective-metrics"><div><small>HORAS PREVISTAS</small><strong>${hours(o.planned_minutes*60)}</strong></div><div><small>HORAS REGISTRADAS</small><strong>${hours(o.effective_seconds)}</strong></div><div><small>PRÓXIMO AFAZER</small>${nextTask(o)}</div></div>
    <button class="button primary" data-action="detail">Ver objetivo completo <span aria-hidden="true">→</span></button>
    <div class="objective-recent"><p class="eyebrow">${activity.length?'SEU AVANÇO NO CAMINHO':'POR ONDE COMEÇAR'}</p>${activity.length?activity.map(t=>`<div class="objective-recent-row"><span>${t.status==='completed'?'✓':'○'} &nbsp; ${esc(t.title)}</span>${t.needs_review?'<span class="objective-review-flag">Revisar</span>':badge(t)}</div>`).join(''):`<p class="muted">${esc(o.next_task?.description || 'Abra o objetivo para conferir as etapas e seus requisitos.')}</p>`}</div>${timeExplanation()}`;
}
function taskRow(t) {
  const requires = t.requires.map(key=>tasks().find(x=>x.task_key===key)).filter(Boolean);
  const check = t.source
    ? `<span class="objective-check ${t.status==='completed'?'done':''}" title="Conclusão acompanhada no registro vinculado" aria-label="${labels[t.status]} na origem">${t.status==='completed'?'✓':''}</span>`
    : `<input type="checkbox" data-complete="${t.id}" aria-label="Concluir ${esc(t.title)}" ${t.status==='completed'?'checked':''} ${current.archived_at?'disabled':''}>`;
  return `<article class="objective-task" id="objective-task-${t.id}" data-task="${t.id}" tabindex="-1">${check}
    <div><h3>${esc(t.title)}</h3><p>${esc(t.description)}</p></div>
    <div class="objective-source">${t.source?sourceLink(t.source):'<span class="muted">Afazer independente</span>'}${t.source&&t.status==='completed'?'<span class="source-completed">✓ Concluído na origem</span>':''}${requires.map(r=>`<button class="objective-requirement ${t.pending_requires.includes(r.task_key)?'pending':''}" data-action="jump" data-task-id="${r.id}" title="Ir para o pré-requisito">${r.needs_review?'Revisar':r.status==='completed'?'✓ Requisito':'Pré-requisito'}: ${esc(r.title)}</button>`).join('')}</div>
    <div class="task-time"><small>Previstas</small>${hours(t.planned_minutes*60)}</div><div class="task-time"><small>Registradas</small>${t.source?hours(t.effective_seconds):'—'}</div>
    <div class="objective-task-controls"><button class="objective-status ${t.status}" data-action="task" data-task-id="${t.id}" aria-label="Estado e revisão de ${esc(t.title)}">${labels[t.status]} <span aria-hidden="true">⌄</span></button>${t.needs_review?'<span class="objective-review-flag">⚑ Revisar depois</span>':''}</div></article>`;
}
function renderDetail(reset = false) {
  const o = current, panel = $('#objective-detail');
  if (!o) return;
  const opened = new Set([...panel.querySelectorAll('details[open][data-stage]')].map(x=>x.dataset.stage));
  const fresh = reset || panel.dataset.objective !== String(o.id);
  panel.dataset.objective = o.id;
  panel.innerHTML = `<a class="text-button" href="/objectives?objective=${o.id}" data-action="home">← Meus objetivos</a>
    <header class="page-heading"><div><p class="eyebrow">${o.archived_at?'OBJETIVO ARQUIVADO':'OBJETIVO DE ESTUDO'}</p><h1>${esc(o.title)}<span>.</span></h1><p class="muted">${esc(o.description)}</p></div><div class="actions"><button class="button secondary" data-action="metadata">Editar</button><button class="button primary" data-action="revise" ${o.archived_at?'disabled':''}>↻ Revisar caminho</button><button class="icon-button" data-action="options" aria-label="Mais opções do objetivo">⋯</button></div></header>
    <div class="card objective-summary"><div><small>Progresso do objetivo</small><div class="summary-progress"><strong>${o.progress}%</strong>${progress(o.progress)}</div></div><div><small>Horas previstas</small><strong>${hours(o.planned_minutes*60)}</strong></div><div><small>Horas registradas</small><strong>${hours(o.effective_seconds)}</strong></div><div><small>Próximo afazer</small>${nextTask(o)}</div></div>
    <div class="objective-tools"><h2>Etapas do objetivo</h2><div class="actions"><button class="text-button" data-action="expand">Expandir todas</button><label class="sr-only" for="objective-stage-filter">Filtrar etapa</label><select id="objective-stage-filter"><option value="">Todas as etapas</option>${o.stages.map(s=>`<option value="${s.id}" ${stageFilter===String(s.id)?'selected':''}>${esc(s.title)}</option>`).join('')}</select><label class="sr-only" for="objective-state-filter">Filtrar estado</label><select id="objective-state-filter"><option value="">Todos os estados</option>${Object.entries({...labels,review:'Revisar depois',blocked:'Requisitos pendentes'}).map(([key,title])=>`<option value="${key}" ${stateFilter===key?'selected':''}>${title}</option>`).join('')}</select></div></div>
    <div id="objective-stage-list">${o.stages.filter(s=>!stageFilter||stageFilter===String(s.id)).map(s=>{
      const filtered = s.tasks.filter(t=>!stateFilter || (stateFilter==='review'?t.needs_review:stateFilter==='blocked'?t.pending_requires.length>0&&t.status!=='completed':t.status===stateFilter));
      if (!filtered.length) return '';
      const isOpen = stageFilter||stateFilter||(fresh?s.completed<s.tasks.length||s.tasks.some(t=>t.needs_review):opened.has(String(s.id)));
      return `<details class="objective-stage" data-stage="${s.id}" ${isOpen?'open':''}><summary><span class="objective-stage-number ${s.completed===s.tasks.length?'done':''}">${s.completed===s.tasks.length?'✓':s.position+1}</span><div><h3>${s.position+1}. ${esc(s.title)}</h3><p>${esc(s.description)}</p></div><small><b>${s.completed} de ${s.tasks.length} afazeres</b><span>${hours(s.effective_seconds)} / ${hours(s.planned_minutes*60)}</span></small></summary><div class="objective-task-list">${filtered.map(taskRow).join('')}</div></details>`;
    }).join('') || '<p class="muted">Nenhum afazer neste filtro.</p>'}</div>${timeExplanation()}`;
}
async function loadList() {
  objectives = await api('/objectives'+($('#objectives-archived').checked?'?archived=1':''));
}
async function select(id, view='overview', push=true) {
  const sequence = ++requestSequence;
  const value = await api('/objectives/'+id);
  if (sequence!==requestSequence) return;
  current = value;
  $('#objectives-archived').checked = !!value.archived_at;
  await loadList();
  renderCards();renderSelected();renderDetail(true);
  if (push) navigate(view); else show(view);
}
async function home(push=true) {
  await loadList();
  const id = objectives.find(o=>o.id===current?.id)?.id || objectives[0]?.id;
  if (id) await select(id,'overview',push);
  else {current=null;renderCards();renderSelected();if(push)navigate('overview',null);else show('overview');}
  editor.resumeBanner();
}
function jump(id) {
  stageFilter='';stateFilter='';renderDetail();
  if ($('#objective-detail').hidden) navigate('detail');
  const row = $('#objective-task-'+id);
  if (!row) return;
  row.closest('details').open=true;
  row.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
  row.focus({preventScroll:true});row.classList.add('objective-highlight');
}
async function refresh(value) {
  current=value;await loadList();renderCards();renderSelected();renderDetail();
}
async function mutateTask(t, values) {
  const id=current.id, version=current.version;
  try {await refresh(await send(`/objectives/${id}/tasks/${t.id}`,{version,...values},'PATCH'));}
  catch(e) {
    if (e.status===409) {
      await refresh(await api('/objectives/'+id));
      e.message='Este item mudou em outra aba. O caminho foi atualizado; reabra o item para conferir antes de alterar.';
    }
    throw e;
  }
}
function editTask(t) {
  const source = t.source, archived=!!current.archived_at;
  const el=dialog(t.title,`${source?`<div class="task-origin">${sourceLink(source)}<p>O estado vem deste registro: <strong>${labels[t.status]}</strong>.</p></div>`:`<label>Estado<select name="status" ${archived?'disabled':''}>${Object.entries(labels).map(([v,l])=>`<option value="${v}" ${t.status===v?'selected':''}>${l}</option>`).join('')}</select></label>`}<p class="muted">${esc(t.description)}</p><label class="check-line"><input type="checkbox" name="needs_review" ${t.needs_review?'checked':''} ${archived?'disabled':''}> Revisar depois</label><p class="field-help">Marcar revisão mantém a conclusão.${source?.kind==='topic'?' A revisão também aparece no conteúdo da disciplina.':''}</p>`,archived?null:async values=>{
    await mutateTask(t,{...(!source?{status:values.status}:{}),needs_review:values.needs_review==='on',source_version:source?.version});
    toast('Afazer atualizado.');
  });
  return el;
}
function editMetadata() {
  const id=current.id, version=current.version;
  dialog('Editar objetivo',`<label>Objetivo<input name="title" value="${esc(current.title)}" maxlength="200" required></label><label>Resultado esperado<textarea name="description" maxlength="5000">${esc(current.description)}</textarea></label>`,async values=>refresh(await send('/objectives/'+id,{...values,version},'PATCH')));
}
function options() {
  const id=current.id, version=current.version, archived=!current.archived_at;
  dialog(archived?'Arquivar objetivo':'Restaurar objetivo',`<p>${archived?'O caminho sai da lista principal. Os afazeres e seus vínculos permanecem guardados.':'O caminho voltará à lista principal.'}</p>`,async()=>{
    await send('/objectives/'+id,{version,archived},'PATCH');$('#objectives-archived').checked=false;await home();
  },archived?'Arquivar':'Restaurar');
}
const editor = new ObjectiveEditor({
  show:()=>navigate('create'), fail,
  saved:async value=>{current=value;$('#objectives-archived').checked=false;await loadList();renderCards();renderSelected();stageFilter='';stateFilter='';renderDetail(true);navigate('detail');toast('Objetivo salvo.');},
});
root.addEventListener('click',async event=>{
  const button=event.target.closest('[data-action],[data-select]');
  if(!button||busy)return;
  event.preventDefault();busy=true;
  $('#objectives-error').textContent='';
  try {
    if(button.dataset.select){await select(Number(button.dataset.select));return;}
    const action=button.dataset.action;
    if(action==='new')await editor.start();
    else if(action==='home')await home();
    else if(action==='detail'){await select(current.id,'detail');}
    else if(action==='jump')jump(Number(button.dataset.taskId));
    else if(action==='expand')$('#objective-detail').querySelectorAll('details[data-stage]').forEach(el=>el.open=true);
    else if(action==='metadata')editMetadata();
    else if(action==='options')options();
    else if(action==='task')editTask(tasks().find(t=>t.id===Number(button.dataset.taskId)));
    else if(action==='revise')await editor.revise(current);
    else await editor.action(action,button);
  }catch(e){fail(e);}finally{busy=false;}
});
root.addEventListener('change',async event=>{
  const el=event.target;
  if(el.id==='objective-stage-filter'){stageFilter=el.value;renderDetail();return;}
  if(el.id==='objective-state-filter'){stateFilter=el.value;renderDetail();return;}
  if(el.id==='objectives-archived'){try{current=null;await home();}catch(e){fail(e);}return;}
  if(!el.dataset.complete)return;
  if(busy){renderDetail();return;}
  busy=true;
  try{const t=tasks().find(t=>t.id===Number(el.dataset.complete));await mutateTask(t,{status:el.checked?'completed':'not_started'});}
  catch(e){renderDetail();fail(e);}finally{busy=false;}
});
async function route() {
  const q=new URLSearchParams(location.search),id=Number(q.get('objective'));
  $('#objectives-archived').checked=q.get('archived')==='1';
  if(q.get('view')==='create' && editor.hasDraft())await editor.resume(false);
  else if(id)await select(id,q.get('view')==='detail'?'detail':'overview',false);
  else await home(false);
  editor.resumeBanner();
}
window.addEventListener('popstate',()=>route().catch(fail));
document.addEventListener('visibilitychange',async()=>{
  if(document.hidden||busy||!$('#objective-create').hidden||$('#common-dialog').open||!current)return;
  try {await refresh(await api('/objectives/'+current.id));}catch(e){fail(e);}
});
route().catch(fail);
