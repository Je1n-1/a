import {$,$$,esc,statuses,hours,options,field,dialog,api,notify,announce,onUpdated,openDialog,bindSubmit,closeSaved,chooseCompletion,operationKey} from './workspace-ui.js';
import {comparisonSide} from './equivalence-preview.js';

const id=Number($('#subject-workspace').dataset.curriculumId);
const endpoint=`/api/curriculum-workspace/${id}`;
const topicStatuses={not_started:'Não iniciado',in_progress:'Em andamento',completed:'Concluído',paused:'Pausado (legado)',for_review:'Para revisar (legado)'};
let data, candidates, request=0, pending=false;
const tab=()=>new URLSearchParams(location.search).get('tab')||'overview';
const date=value=>value?new Intl.DateTimeFormat('pt-BR',{timeZone:'America/Sao_Paulo'}).format(new Date(value.length===10?value+'T12:00:00-03:00':value)):'Não informada';
const assessment=value=>value==null?'Não informado':value===0?'0 · valor histórico':`${value} / 5`;
const formFooter=label=>`<p class="form-error" role="alert"></p><div class="form-actions"><button type="button" data-close>Cancelar</button><button type="submit" class="primary">${label}</button></div>`;
const subjectLink=row=>`<a class="subject-link" href="/curriculum/${row.id}">${esc(row.name)} · ${esc(row.formation_name)}</a>`;
const editable=()=>!data.curriculum.archived_at&&!data.curriculum.formation_archived_at;
const editDisabled=()=>editable()?'':'disabled';
function assessmentField(label,name,value){return `<label class="field">${label}<select name="${name}"><option value="" ${value==null?'selected':''}>Não informado</option>${value===0?'<option value="0" selected>0 · valor histórico (preservado)</option>':''}${[1,2,3,4,5].map(n=>`<option value="${n}" ${value===n?'selected':''}>${n}</option>`).join('')}</select></label>`;}
function fail(error){$('#load-error').hidden=false;$('#load-error').textContent=error.message;}
async function refresh(){
  const token=++request;
  const [next,links]=await Promise.all([api(endpoint),api(endpoint+'/equivalences')]);
  if(token!==request)return;
  data=next;candidates=links;$('#load-error').hidden=true;render();
}
function render(){
  const c=data.curriculum,p=data.content_progress;
  document.title=`${c.name} · Plano`;
  const back=new URLSearchParams(location.search).get('return');
  const validBack=back&&/^\/(formations|subjects|today)(?:\?|$)/.test(back);
  $('#back-to-formation').href=validBack?back:`/formations?course=${c.formation_id}`;
  $('#back-to-formation').textContent=validBack&&back.startsWith('/subjects')?'← Voltar às disciplinas':'← Voltar à formação';
  $('#subject-hero').innerHTML=`<header class="subject-hero"><div class="eyebrow">SUA TRAJETÓRIA · DISCIPLINA</div><div class="hero-heading"><div><h1>${esc(c.name)}</h1><p><a href="/formations?course=${c.formation_id}">${esc(c.formation_name)}</a> <span class="crumb">/</span> ${esc(c.period||'Sem período definido')}${c.code?' · '+esc(c.code):''}</p></div><button data-action="edit" class="secondary-small" ${editDisabled()}>Editar disciplina</button></div>${data.linked_subjects.length?`<div class="shared-caption">↔ Compartilhada com ${data.linked_subjects.map(subjectLink).join(' · ')}</div>`:''}${!editable()?'<p class="notice">Consulta de registro arquivado. Restaure-o em sua formação para editar.</p>':''}<div class="subject-metrics"><div><span>Situação acadêmica</span><strong class="status-${c.academic_status}">${statuses[c.academic_status]}</strong></div><div><span>Carga curricular</span><strong>${hours(c.workload_minutes)}</strong></div><div><span>Conteúdo organizado</span><strong>${p.total?`${p.completed} de ${p.total} tópicos`:'Sem tópicos cadastrados'}</strong></div><div><span>Domínio pessoal</span><strong>${assessment(data.personal.mastery)}</strong></div></div></header>`;
  for(const link of $$('.subject-tabs a')){
    const q=new URLSearchParams(location.search);q.set('tab',link.dataset.tab);link.href=`?${q}`;
    if(link.dataset.tab===tab())link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
  }
  if(tab()==='contents')renderContents();else if(tab()==='equivalences')renderEquivalences();else renderOverview();
  if(validBack&&back.startsWith('/today'))$('#back-to-formation').textContent='← Voltar a Hoje';
  if(editable())$('.hero-heading',$('#subject-hero')).insertAdjacentHTML('beforeend',`<a class="subject-link" href="/today?curriculum=${id}">Começar estudo →</a>`);
}
function renderOverview(){
  const c=data.curriculum,p=data.content_progress;
  $('#subject-panel').innerHTML=`<div class="overview-grid"><section class="subject-card"><div class="section-heading"><h2>Informações acadêmicas</h2><button data-action="edit" class="text-button" ${editDisabled()}>Editar dados</button></div><dl class="facts"><div><dt>Formação</dt><dd>${esc(c.formation_name)}</dd></div><div><dt>Período / módulo</dt><dd>${esc(c.period||'Não informado')}</dd></div><div><dt>Início</dt><dd>${date(c.start_date)}</dd></div><div><dt>Data final</dt><dd>${date(c.end_date)}</dd></div><div><dt>Carga curricular</dt><dd>${hours(c.workload_minutes)}</dd></div><div><dt>Código</dt><dd>${esc(c.code||'Não informado')}</dd></div></dl><p class="small-note">A carga pertence à grade do curso. Não representa tempo pessoal obrigatório de estudo.</p><h3>Observações</h3><p class="preserve-lines">${esc(c.notes||'Nenhuma observação registrada.')}</p>${c.academic_status!=='completed'?`<button data-action="complete" class="primary" ${editDisabled()}>Marcar como concluída</button>`:data.linked_subjects.some(r=>r.academic_status!=='completed')?`<button data-action="complete" ${editDisabled()}>Aproveitar conclusão em outro curso</button>`:''}</section><section class="subject-card"><div class="section-heading"><h2>Sua percepção</h2><button data-action="assess" class="text-button" ${editDisabled()}>Editar autoavaliações</button></div><div class="perception"><div><span>Dificuldade</span><strong>${assessment(data.personal.difficulty)}</strong><p>Como você percebe a dificuldade desta matéria.</p></div><div><span>Domínio</span><strong>${assessment(data.personal.mastery)}</strong><p>Quanto você considera que compreende o conteúdo.</p></div></div><p class="small-note">São opcionais. Não geram agenda ou prioridade automática.${data.linked_subjects.length?' Compartilhadas com as disciplinas vinculadas.':''}</p><div class="content-summary"><h3>Progresso dos conteúdos</h3><p>${p.total?`${p.completed} de ${p.total} tópicos concluídos · ${p.percent}%`:'Sem tópicos cadastrados. Organize o conteúdo quando fizer sentido para você.'}</p><a class="subject-link" href="${tabUrl('contents')}">Ver conteúdos →</a></div></section></div><section class="subject-card history-card"><h2>Registros desta disciplina</h2><p class="small-note">Conclusão acadêmica, tópicos e domínio são informações independentes.</p><details><summary>Histórico acadêmico (${data.history.length})</summary>${data.history.length?data.history.map(r=>`<div class="history-row"><strong>${statuses[r.academic_status]}</strong><span>${date(r.created_at)}</span><p>${esc(r.notes||'Situação atualizada pelo usuário.')}</p></div>`).join(''):'<p>Nenhuma mudança de situação registrada.</p>'}</details><details><summary>Autoavaliações registradas (${data.assessment_history.length})</summary>${data.assessment_history.length?data.assessment_history.map(r=>`<div class="history-row"><strong>${r.kind==='mastery'?'Domínio':'Dificuldade'}${r.topic_id?' · tópico #'+r.topic_id:''}: ${assessment(r.value)}</strong><span>${date(r.recorded_at)}</span><p>${r.origin==='manual'?'Informado por você':'Preservado no vínculo entre cursos'}</p></div>`).join(''):'<p>Nenhuma autoavaliação registrada.</p>'}</details>${resourceHistory()}</section>`;
}
function tabUrl(name){const q=new URLSearchParams(location.search);q.set('tab',name);return '?'+q;}
function resourceHistory(){
  const r=data.resources;
  return `<details><summary>Histórico de estudo preservado (${r.session_count} sessões · ${r.note_count} notas)</summary>${r.sessions.map(s=>`<div class="history-row"><strong>${date(s.date)} · ${hours(s.duration_seconds/60)}</strong><p>Registro #${s.id} · estudo de origem #${s.study_subject_id}</p>${s.notes?`<p class="preserve-lines">${esc(s.notes)}</p>`:''}</div>`).join('')}${r.notes.map(n=>`<div class="history-row"><strong>${esc(n.title)}</strong><p>Nota #${n.id} · estudo de origem #${n.study_subject_id}</p><p class="preserve-lines">${esc(n.content_markdown)}</p></div>`).join('')}${!r.session_count&&!r.note_count?'<p>Nenhuma sessão ou nota registrada.</p>':''}</details>`;
}
function renderContents(){
  const active=data.contents.filter(t=>!t.archived_at),archived=data.contents.filter(t=>t.archived_at);
  const editableIds=active.filter(t=>!t.read_only).map(t=>t.id);
  const row=(t,position)=>{
    const index=editableIds.indexOf(t.id);
    const quickComplete=t.status!=='completed'?`<button data-action="complete-topic" data-topic="${t.id}" aria-label="Concluir ${esc(t.name)}" ${editDisabled()}>Concluir</button>`:'';
    return `<article class="topic-row" data-topic-row="${t.id}" tabindex="-1" aria-label="${esc(t.name)}">
      <div class="topic-order">${position+1}</div>
      <div class="topic-info"><h3>${esc(t.name)}</h3><p>${esc(t.description||'')}</p>
        <div class="topic-meta">${t.archived_at?'<span class="badge">Arquivado</span>':''}<span class="badge">${topicStatuses[t.status]||esc(t.status)}</span><span>Domínio: ${assessment(t.assessment_mastery)}</span><span>${esc(t.origin_name)}</span></div>
        ${t.read_only?'<p class="small-note">Referência preservada após desvincular. Edição na formação de origem.</p>':''}
      </div>
      <div class="row-actions">${t.read_only?`<a class="subject-link" href="/curriculum/${t.origin_curriculum_id}?tab=contents">Ver origem</a>`:t.archived_at?`<button data-action="restore" data-topic="${t.id}" ${editDisabled()}>Restaurar</button>`:`
        <button data-action="move-up" data-topic="${t.id}" aria-label="Subir ${esc(t.name)}" ${index<=0?'disabled':editDisabled()}>↑</button>
        <button data-action="move-down" data-topic="${t.id}" aria-label="Descer ${esc(t.name)}" ${index===editableIds.length-1?'disabled':editDisabled()}>↓</button>
        ${quickComplete}<button data-action="edit-topic" data-topic="${t.id}" ${editDisabled()}>Editar</button><button data-action="remove-topic" data-topic="${t.id}" ${editDisabled()}>Remover</button>`}
      </div></article>`;
  };
  $('#subject-panel').innerHTML=`<section class="subject-card"><div class="section-heading"><div><h2>Conteúdos da disciplina</h2><p>Organize os assuntos no seu ritmo. Tópicos são opcionais.</p></div><button data-action="add-topic" class="primary" ${editDisabled()}>＋ Adicionar tópico</button></div>${active.length?`<div class="topic-list">${active.map(row).join('')}</div>`:'<div class="empty"><strong>Sem tópicos cadastrados</strong>Adicione os assuntos que deseja organizar, quando precisar.</div>'}${archived.length?`<details class="archived-topics"><summary>Tópicos arquivados (${archived.length})</summary>${archived.map(row).join('')}</details>`:''}<p class="small-note">Concluir tópicos não conclui a disciplina e não altera seu domínio.</p></section>`;
}
function renderEquivalences(){
  const candidateCard=(r,separated=false)=>`<article class="equivalence-row"><div><h3>${esc(r.name)}</h3><p>${esc(r.formation_name)} · ${hours(r.workload_minutes)}</p><span class="badge">${statuses[r.academic_status]}</span></div><div class="row-actions"><button data-action="compare" data-other="${r.id}" ${editDisabled()}>Comparar</button><button data-action="${separated?'reconsider':'separate'}" data-other="${r.id}" ${editDisabled()}>${separated?'Rever decisão':'Manter separado'}</button></div></article>`;
  $('#subject-panel').innerHTML=`<section class="subject-card"><div class="section-heading"><div><h2>Compartilhada com</h2><p>Conteúdos e autoavaliações em comum. Situação, carga e datas independentes.</p></div>${candidates.linked.length?`<button data-action="unlink" ${editDisabled()}>Desvincular desta matéria</button>`:''}</div>${candidates.linked.length?candidates.linked.map(r=>`<article class="equivalence-row"><div><h3>${subjectLink(r)}</h3><p>${hours(r.workload_minutes)} · ${esc(r.period||'Sem período definido')}</p><span class="badge">${statuses[r.academic_status]}</span></div><a class="subject-link" href="/formations?course=${r.formation_id}">Ver formação →</a></article>`).join(''):'<p>Nenhum vínculo confirmado.</p>'}</section><section class="subject-card"><h2>Possíveis correspondências</h2><p class="small-note">Nome parecido é apenas um indício. Compare antes de decidir.</p>${candidates.candidates.length?candidates.candidates.map(r=>candidateCard(r)).join(''):'<div class="empty">Nenhuma correspondência pendente encontrada.</div>'}</section>${candidates.separated.length?`<section class="subject-card"><details><summary>Mantidas separadas (${candidates.separated.length})</summary>${candidates.separated.map(r=>candidateCard(r,true)).join('')}</details></section>`:''}`;
}
async function mutate(suffix,values,method='POST'){
  const result=await api(endpoint+suffix,{method,body:JSON.stringify({operation_key:(dialog.open&&$('#dialog-body form')?.dataset.operationKey)||operationKey(),...values})});
  announce(result.affected);return result;
}
async function afterSave(message){closeSaved();await refresh();notify(message);}
async function editAcademic(){
  const c=data.curriculum,formations=await api('/api/formations');
  openDialog('Editar disciplina',`<form><div class="form-grid">${field('Nome','name',c.name,'text','required maxlength="200"')}${field('Código (opcional)','code',c.code||'')}<label class="field full">Formação<select name="formation_id">${formations.map(f=>`<option value="${f.id}" ${f.id===c.formation_id?'selected':''}>${esc(f.name)}</option>`).join('')}</select></label>${field('Período / módulo','period',c.period||'')}${field('Carga curricular em horas (opcional)','hours',c.workload_minutes==null?'':c.workload_minutes/60,'number','min="0.01" step="0.01"')}<label class="field">Situação acadêmica<select name="academic_status">${options(c.academic_status)}</select></label>${field('Início (opcional)','start_date',c.start_date||'','date')}${field('Data final (opcional)','end_date',c.end_date||'','date')}<label class="field full">Observações (opcional)<textarea name="notes">${esc(c.notes||'')}</textarea></label></div>${formFooter('Salvar disciplina')}</form>`);
  bindSubmit(async form=>{
    const values=Object.fromEntries(new FormData(form));values.workload_minutes=values.hours===''?null:Math.round(Number(values.hours)*60);delete values.hours;
    if(values.academic_status==='completed'){const choice=await chooseCompletion(id);if(!choice)return;Object.assign(values,choice);}
    values.expected_updated_at=c.updated_at;await mutate('',values,'PATCH');await afterSave('Disciplina salva.');
  });
}
function editAssessments(){
  openDialog('Suas autoavaliações',`<form><p>Dificuldade é sua percepção; domínio é sua avaliação de compreensão. Deixe em branco quando não quiser avaliar.</p><div class="form-grid assessment-fields">${assessmentField('Dificuldade (opcional)','difficulty',data.personal.difficulty)}${assessmentField('Domínio (opcional)','mastery',data.personal.mastery)}</div>${data.linked_subjects.length?'<p class="notice">Esta avaliação será compartilhada com as matérias vinculadas.</p>':''}${formFooter('Salvar autoavaliações')}</form>`);
  bindSubmit(async form=>{await mutate('',{...Object.fromEntries(new FormData(form)),expected_personal_updated_at:data.personal.updated_at},'PATCH');await afterSave('Autoavaliações registradas com data.');});
}
function editTopic(topic){
  const statusesForTopic=Object.entries(topicStatuses).filter(([key])=>!['paused','for_review'].includes(key)||topic?.status===key);
  openDialog(topic?'Editar tópico':'Adicionar tópico',`<form><div class="form-grid">${field('Nome do tópico','name',topic?.name||'','text','required maxlength="200"')}<label class="field">Situação<select name="status">${statusesForTopic.map(([v,l])=>`<option value="${v}" ${v===topic?.status?'selected':''}>${l}</option>`).join('')}</select></label>${assessmentField('Domínio do tópico (opcional)','mastery',topic?.assessment_mastery)}<label class="field full">Descrição (opcional)<textarea name="description">${esc(topic?.description||'')}</textarea></label></div>${formFooter('Salvar tópico')}</form>`);
  bindSubmit(async form=>{
    const values=Object.fromEntries(new FormData(form));
    if(topic){
      values.expected_updated_at=topic.updated_at;
      if(values.mastery===String(topic.assessment_mastery??''))delete values.mastery;
    }
    await mutate('/contents'+(topic?'/'+topic.id:''),values,topic?'PATCH':'POST');await afterSave('Tópico salvo.');
  });
}
async function removeTopic(topicId){
  const preview=await api(endpoint+`/contents/${topicId}/removal`),archive=preview.action==='archive';
  openDialog(archive?'Arquivar tópico?':'Excluir tópico?',`<form><p><strong>${esc(preview.topic.name)}</strong></p><p>${archive?'Há histórico ou referências associados. O tópico será arquivado, continuará disponível para consulta e poderá ser restaurado.':'Este tópico não tem histórico nem referências. A exclusão é definitiva.'}</p>${formFooter(archive?'Arquivar tópico':'Excluir tópico')}</form>`);
  bindSubmit(async()=>{await mutate(`/contents/${topicId}/removal`,{confirmed:true,action:preview.action});await afterSave(archive?'Tópico arquivado.':'Tópico excluído.');});
}
async function moveTopic(topicId,direction){
  const ids=data.contents.filter(t=>!t.archived_at&&!t.read_only).map(t=>t.id),i=ids.indexOf(topicId),j=i+direction;if(j<0||j>=ids.length)return;
  [ids[i],ids[j]]=[ids[j],ids[i]];await mutate('/contents/order',{topic_ids:ids,expected_version:data.contents_version});await refresh();
  const button=$(`[data-topic="${topicId}"][data-action="${direction<0?'move-up':'move-down'}"]`);
  (button&&!button.disabled?button:$(`[data-topic-row="${topicId}"]`))?.focus();notify('Ordem atualizada.');
}
async function completeTopic(topicId){
  const topic=data.contents.find(t=>t.id===topicId);
  await mutate(`/contents/${topicId}`,{status:'completed',expected_updated_at:topic.updated_at},'PATCH');
  await refresh();$(`[data-topic-row="${topicId}"]`)?.focus();
  notify('Tópico concluído. A situação acadêmica e o domínio foram mantidos.');
}
async function complete(sourceId=id){
  const choice=await chooseCompletion(sourceId);if(!choice)return;
  const result=await api(`/api/curriculum-workspace/${sourceId}/completion`,{method:'POST',body:JSON.stringify({...choice,operation_key:operationKey()})});
  announce(result.affected);await refresh();notify('Conclusão registrada nas formações escolhidas.');
}
async function compare(other){
  const preview=await api(endpoint+`/equivalences/${other}`);
  const side=comparisonSide;
  openDialog('Comparar disciplinas',`<form><div class="compare-grid">${preview.sides.map(side).join('')}</div><p class="notice">Todos os tópicos e históricos serão preservados na origem, inclusive títulos repetidos. Situação acadêmica, carga, datas e observações continuam independentes.</p>${preview.members.length>2?`<p>Este vínculo reúne ${preview.members.length} formações: ${preview.members.map(r=>esc(r.formation_name)).join(', ')}.</p>`:''}${preview.conflicts.length?`<h3>Escolha as autoavaliações em conflito</h3><div class="form-grid assessment-fields">${preview.conflicts.map(key=>`<label class="field">${key==='mastery'?'Domínio':'Dificuldade'} compartilhado<select name="${key}" required><option value="">Escolha uma avaliação</option>${preview.sides.map(s=>`<option value="${s.curriculum.id}">${esc(s.curriculum.formation_name)} · ${assessment(s.personal[key])}</option>`).join('')}</select></label>`).join('')}</div>`:''}<p class="small-note">A matéria mais antiga será a referência inicial. Vincular não inicia estudos nem conclui disciplinas.</p>${formFooter('Confirmar vínculo')}</form>`,'CONFERIR ANTES DE VINCULAR',true);
  bindSubmit(async form=>{
    const choices=Object.fromEntries([...new FormData(form)].map(([k,v])=>[k,Number(v)]));
    const result=await mutate(`/equivalences/${other}`,{confirmed:true,version:preview.version,assessment_choices:choices});
    await afterSave('Vínculo confirmado. Conteúdos compartilhados.');
    if(result.completion_offer)await complete(result.completion_offer.source.id);
  });
}
async function unlink(){
  const preview=await api(endpoint+'/unlink');
  openDialog('Desvincular esta disciplina?',`<form><p>Será removido o vínculo de <strong>${esc(data.curriculum.name)} · ${esc(data.curriculum.formation_name)}</strong> com ${data.linked_subjects.map(r=>esc(r.formation_name)).join(', ')}.</p><div class="notice">Continuam acessíveis: ${preview.counts.topics} tópicos, ${preview.counts.sessions} sessões e ${preview.counts.notes} notas.</div><p>${esc(preview.message)}</p><p class="small-note">Nenhuma situação acadêmica será alterada. As autoavaliações atuais serão preservadas em cada lado.</p>${formFooter('Confirmar desvinculação')}</form>`);
  bindSubmit(async()=>{await mutate('/unlink',{confirmed:true,version:preview.version});await afterSave('Vínculo removido. Histórico preservado.');});
}
$('#subject-workspace').addEventListener('click',async e=>{
  const target=e.target.closest('[data-action]');if(!target)return;
  const action=target.dataset.action,topicId=Number(target.dataset.topic),other=Number(target.dataset.other);
  target.disabled=true;
  try{
    if(action==='edit')await editAcademic();
    else if(action==='assess')editAssessments();
    else if(action==='complete')await complete();
    else if(action==='add-topic')editTopic();
    else if(action==='edit-topic')editTopic(data.contents.find(t=>t.id===topicId));
    else if(action==='complete-topic')await completeTopic(topicId);
    else if(action==='remove-topic')await removeTopic(topicId);
    else if(action==='restore'){await mutate(`/contents/${topicId}/restore`,{});await refresh();notify('Tópico restaurado.');}
    else if(action==='move-up'||action==='move-down')await moveTopic(topicId,action==='move-up'?-1:1);
    else if(action==='compare')await compare(other);
    else if(action==='separate'||action==='reconsider'){await mutate(`/equivalences/${other}/decision`,{decision:action==='separate'?'separate':'reconsider'});await refresh();notify('Decisão salva.');}
    else if(action==='unlink')await unlink();
  }catch(error){notify(error.message);}finally{target.disabled=false;}
});
onUpdated(event=>{
  if(!event.curriculum_ids?.includes(id)&&!event.formation_ids?.includes(data?.curriculum.formation_id))return;
  if(dialog.open||document.querySelector('#completion-title')){pending=true;notify('Os dados mudaram em outra aba. Sua edição foi mantida; feche para atualizar.');return;}
  refresh().catch(fail);
});
dialog.addEventListener('close',()=>{if(pending){pending=false;refresh().catch(fail);}});
refresh().catch(fail);
