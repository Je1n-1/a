import {$,esc,api,send,dialog,toast} from './api.js';
import {clock,date,timestamp} from './study-format.js';
const statusLabels={not_started:'Não iniciado',in_progress:'Em andamento',completed:'Concluído'};
let projects=[],courses=[],current=null;
const target=(id,step)=>`/?project=${id}${step?'&step='+step:''}`;
const progress=p=>`<div class="project-progress"><span>${p.completed_steps} de ${p.step_count} etapas concluídas</span><strong>${clock(p.effective_seconds)} registrados</strong></div><div class="project-track" aria-hidden="true"><span style="width:${p.step_count?100*p.completed_steps/p.step_count:0}%"></span></div>`;
function renderList(){
  const filter=$('#project-status').value,q=$('#project-search').value.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  const rows=projects.filter(p=>(filter==='archived'?p.archived_at:!p.archived_at&&(filter==='all'||(filter==='active'?p.status!=='completed':p.status==='completed')))&&(p.name+' '+p.objective+' '+(p.course_name||'')).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().includes(q));
  $('#project-cards').innerHTML=rows.length?rows.map(p=>`<article class="card project-card"><h2>${esc(p.name)}</h2><span class="project-meta">${esc(p.course_name||'Projeto independente')} · ${p.archived_at?'Arquivado':statusLabels[p.status]}</span><p class="project-objective muted">${esc(p.objective||'Sem objetivo informado.')}</p>${progress(p)}<div class="actions">${!p.archived_at?`<a class="button primary" href="${target(p.id)}">▶ Trabalhar neste projeto</a>`:''}<a class="button secondary" href="/projects?project=${p.id}">Abrir projeto</a></div></article>`).join(''):'<div class="card empty"><h2>Nenhum projeto nesta lista.</h2><p>Crie um projeto ou ajuste os filtros.</p></div>';
}
async function load(){
  $('#projects-error').textContent='';
  try{
    [projects,courses]=await Promise.all([api('/projects?archived=1'),api('/courses?archived=1')]);
    const id=new URLSearchParams(location.search).get('project');
    $('#projects-list-view').hidden=!!id;$('#project-detail').hidden=!id;
    if(id){current=await api('/projects/'+id);renderDetail();}else{current=null;renderList();}
  }catch(e){$('#projects-error').textContent=e.message;}
}
function editProject(p=null){
  dialog(p?'Editar projeto':'Novo projeto',`<label>Nome do projeto<input name="name" value="${esc(p?.name||'')}" required placeholder="Ex.: Site para o curso"></label><label>Objetivo<textarea name="objective" maxlength="5000" placeholder="O que você quer construir?">${esc(p?.objective||'')}</textarea></label><label>Curso relacionado (opcional)<select name="course_id"><option value="">Projeto independente</option>${courses.filter(c=>!c.archived_at||c.id===p?.course_id).map(c=>`<option value="${c.id}" ${c.id===p?.course_id?'selected':''}>${esc(c.name)}${c.archived_at?' (arquivado)':''}</option>`).join('')}</select></label><label>Situação<select name="status">${Object.entries(statusLabels).map(([key,label])=>`<option value="${key}" ${key===(p?.status||'not_started')?'selected':''}>${label}</option>`).join('')}</select></label><p class="field-help">A conclusão das etapas e a situação do projeto são escolhas separadas. Alterar o curso vale para novas sessões; os registros anteriores mantêm o vínculo original.</p>`,async values=>{
    const result=await send('/projects'+(p?'/'+p.id:''),{...values,course_id:values.course_id?Number(values.course_id):null,...(p?{version:p.version}:{})},p?'PATCH':'POST');
    history.replaceState(null,'','/projects?project='+result.id);await load();toast('Projeto salvo.');
  },p?'Salvar projeto':'Criar projeto');
}
function renderDetail(){
  const p=current,root=$('#project-detail');
  root.innerHTML=`<a class="inline-link" href="/projects">← Todos os projetos</a><article class="card project-overview"><div class="section-heading"><div><p class="eyebrow">${esc(p.course_name||'PROJETO INDEPENDENTE')}</p><h2>${esc(p.name)}</h2></div><span class="badge">${p.archived_at?'Arquivado':statusLabels[p.status]}</span></div><p class="project-objective">${esc(p.objective||'Sem objetivo informado.')}</p>${progress(p)}<div class="actions">${!p.archived_at?`<a class="button primary" href="${target(p.id)}">▶ Trabalhar neste projeto</a><button class="button secondary" data-manual>Registrar tempo</button>`:''}<button class="button secondary" data-edit-project>Editar projeto</button><button class="button ghost" data-archive>${p.archived_at?'Restaurar':'Arquivar'}</button></div></article>
  <div class="project-columns"><section class="card"><div class="section-heading"><h2>Etapas</h2>${!p.archived_at?'<button class="button secondary small" data-add-step>＋ Nova etapa</button>':''}</div><p class="field-help">O progresso mede etapas concluídas. As horas incluem sessões finalizadas.</p><div>${p.steps.length?p.steps.map(s=>`<article class="project-step"><label class="check-line"><input type="checkbox" data-complete-step="${s.id}" ${s.completed?'checked':''} ${p.archived_at?'disabled':''}><span>${esc(s.name)}<small>${clock(s.effective_seconds)} registrados</small></span></label>${!p.archived_at?`<div class="actions"><a class="button secondary small" href="${target(p.id,s.id)}">▶ Trabalhar nesta etapa</a><button class="text-button" data-edit-step="${s.id}">Editar</button></div>`:''}</article>`).join(''):'<p class="muted">Adicione a primeira etapa. Você também pode registrar tempo no projeto sem escolher uma etapa.</p>'}</div></section>
  <section class="card"><div class="section-heading"><h2>O que foi feito</h2><a class="inline-link" href="/analytics?activity=project&project_id=${p.id}">Ver análises ↗</a></div><p class="field-help">Últimas 20 sessões · ${p.session_count} no total · Horários de São Paulo</p>${p.recent.length?p.recent.map(s=>`<article class="project-record"><strong>${esc(s.step_name||'Projeto, sem etapa')}</strong><small>${s.started_at?esc(timestamp(s.started_at)):date(s.local_date)} · ${clock(s.effective_seconds)} líquidos</small><p>${esc(s.note||'Sem anotação nesta sessão.')}</p><small>${clock(s.break_seconds)} de pausas · ${clock(s.rest_seconds)} de intervalos</small></article>`).join(''):'<p class="muted">Suas sessões e anotações aparecerão aqui.</p>'}</section></div>`;
  $('[data-edit-project]',root).onclick=()=>editProject(p);
  $('[data-add-step]',root)?.addEventListener('click',()=>editStep());
  root.querySelectorAll('[data-edit-step]').forEach(b=>b.onclick=()=>editStep(p.steps.find(s=>s.id===Number(b.dataset.editStep))));
  root.querySelectorAll('[data-complete-step]').forEach(input=>input.onchange=async()=>{
    const s=p.steps.find(s=>s.id===Number(input.dataset.completeStep));input.disabled=true;
    try{await send(`/projects/${p.id}/steps/${s.id}`,{completed:input.checked,version:s.version},'PATCH');await load();}
    catch(e){input.checked=!!s.completed;input.disabled=false;toast(e.message);}
  });
  $('[data-archive]',root).onclick=()=>dialog(p.archived_at?'Restaurar projeto?':'Arquivar projeto?',`<p>${p.archived_at?'O projeto voltará à lista.':'O projeto sai da lista ativa. Suas etapas e registros continuam disponíveis no arquivo e nas análises.'}</p>`,async()=>{await send('/projects/'+p.id,{version:p.version,archived:!p.archived_at},'PATCH');await load();},p.archived_at?'Restaurar':'Arquivar');
  $('[data-manual]',root)?.addEventListener('click',async()=>{const {openManual}=await import('./manual-session.js');openManual([],load,{projectId:p.id});});
}
function editStep(s=null){
  const id=current.id;
  dialog(s?'Editar etapa':'Nova etapa',`<label>Nome da etapa<input name="name" value="${esc(s?.name||'')}" required placeholder="Ex.: Montar a tela inicial"></label>`,async values=>{await send(`/projects/${id}/steps${s?'/'+s.id:''}`,{...values,...(s?{version:s.version}:{})},s?'PATCH':'POST');await load();},s?'Salvar etapa':'Adicionar etapa');
}
$('#new-project').onclick=()=>editProject();$('#project-status').onchange=renderList;$('#project-search').oninput=renderList;load();
