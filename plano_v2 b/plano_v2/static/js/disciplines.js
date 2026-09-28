import {$,esc,api,statuses,hours,options,notify,onUpdated} from './workspace-ui.js';
const params=new URLSearchParams(location.search);
const normalize=value=>String(value??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
const state={items:[],q:params.get('q')||'',formation:params.get('formation')||'',status:params.get('status')||''};
const contextChoice=new Map();
let request=0,pending=false;
$('#catalog-query').value=state.q;
$('#catalog-status').innerHTML='<option value="">Todas as situações</option>'+options(state.status);
$('#catalog-status').value=state.status;

function syncUrl(){
  const query=new URLSearchParams();
  if(state.q)query.set('q',state.q);if(state.formation)query.set('formation',state.formation);if(state.status)query.set('status',state.status);
  history.replaceState(null,'','/subjects'+(query.size?'?'+query:''));
}
function matchingContexts(item){return item.contexts.filter(c=>(!state.formation||String(c.formation_id)===state.formation)&&(!state.status||c.academic_status===state.status));}
function selectedContext(item){
  const matching=matchingContexts(item),saved=contextChoice.get(item.key);
  return matching.find(c=>c.id===saved)||matching[0]||item.contexts[0];
}
function destination(item){const c=selectedContext(item);return c?`/curriculum/${c.id}?return=${encodeURIComponent(location.pathname+location.search)}`:null;}
function render(){
  syncUrl();
  const items=state.items.filter(item=>{
    if((state.formation||state.status)&&!matchingContexts(item).length)return false;
    return normalize([item.name,...item.contexts.map(c=>`${c.name} ${c.code||''} ${c.formation_name}`)].join(' ')).includes(normalize(state.q));
  });
  const occurrences=items.reduce((n,r)=>n+r.contexts.length,0);
  $('#catalog-count').textContent=`${items.length} matérias · ${occurrences} ocorrências nas grades. A situação acadêmica pertence a cada formação.`;
  $('#catalog-list').innerHTML=items.length?items.map(item=>{
    const current=selectedContext(item),url=destination(item),mastery=item.personal.mastery;
    return `<article class="catalog-row" data-key="${esc(item.key)}"><div class="catalog-main"><h2>${url?`<a class="subject-link" data-open href="${url}">${esc(item.name)}</a>`:esc(item.name)}</h2>
    <p class="catalog-meta">${item.shared?'<span class="badge">Conteúdos compartilhados</span>':''}<span>Domínio: ${mastery==null?'Não informado':mastery===0?'0 · registro histórico':mastery+'/5'}</span></p>
    ${item.contexts.length?`<ul class="catalog-contexts">${item.contexts.map(c=>`<li><span>${esc(c.formation_name)}${c.name!==item.name?' · '+esc(c.name):''}</span><span class="status-${c.academic_status}">${statuses[c.academic_status]}</span><span>${hours(c.workload_minutes)}</span></li>`).join('')}</ul>`:'<p class="small-note">Estudo pessoal sem vínculo curricular. Seus registros estão preservados; a integração ao estudo manual vem na próxima etapa.</p>'}</div>
    ${current?`<div class="catalog-actions">${item.contexts.length>1?`<label class="field">Contexto acadêmico<select data-context aria-label="Formação de ${esc(item.name)}">${item.contexts.map(c=>`<option value="${c.id}" ${c.id===current.id?'selected':''}>${esc(c.formation_name)} · ${statuses[c.academic_status]}</option>`).join('')}</select></label>`:`<p class="catalog-meta">${esc(current.period||'Sem período definido')}</p>`}<a class="catalog-open" data-open href="${url}">Abrir disciplina →</a></div>`:''}</article>`;
  }).join(''):'<div class="empty"><strong>Nenhuma disciplina encontrada</strong>Altere os filtros ou cadastre uma grade em Formações.</div>';
}
async function refresh(){
  const token=++request;$('#catalog-list').setAttribute('aria-busy','true');
  try{
    const data=await api('/api/curriculum-workspace/catalog');if(token!==request)return;
    state.items=data.items;
    const formations=new Map(data.items.flatMap(r=>r.contexts.map(c=>[String(c.formation_id),c.formation_name])));
    $('#catalog-formation').innerHTML='<option value="">Todas as formações</option>'+[...formations].sort((a,b)=>a[1].localeCompare(b[1])).map(([id,name])=>`<option value="${id}">${esc(name)}</option>`).join('');
    if(!formations.has(state.formation))state.formation='';$('#catalog-formation').value=state.formation;
    $('#catalog-error').hidden=true;render();
  }catch(error){$('#catalog-error').hidden=false;$('#catalog-error span').textContent=error.message;}
  finally{if(token===request)$('#catalog-list').removeAttribute('aria-busy');}
}
$('#catalog-query').oninput=e=>{state.q=e.target.value;render();};
$('#catalog-formation').onchange=e=>{state.formation=e.target.value;render();};
$('#catalog-status').onchange=e=>{state.status=e.target.value;render();};
$('#catalog-clear').onclick=()=>{state.q=state.formation=state.status='';$('#catalog-query').value='';$('#catalog-formation').value='';$('#catalog-status').value='';render();};
$('#catalog-retry').onclick=refresh;
$('#catalog-list').onchange=e=>{
  if(!e.target.matches('[data-context]'))return;
  const row=e.target.closest('[data-key]'),item=state.items.find(i=>i.key===row.dataset.key);
  const c=item.contexts.find(c=>c.id===Number(e.target.value));contextChoice.set(item.key,c.id);
  row.querySelectorAll('[data-open]').forEach(a=>a.href=`/curriculum/${c.id}?return=${encodeURIComponent(location.pathname+location.search)}`);
};
onUpdated(event=>{
  if(!event.formation_ids&&!event.curriculum_ids)return;
  if(document.activeElement?.closest('.catalog-panel')){pending=true;notify('A lista mudou em outra aba. Será atualizada ao terminar sua interação.');}
  else refresh();
});
document.addEventListener('focusout',()=>setTimeout(()=>{if(pending&&!document.activeElement?.closest('.catalog-panel')){pending=false;refresh();}},0));
refresh();
