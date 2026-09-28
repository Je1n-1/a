// Componentes comuns às páginas novas. Não importa o frontend do planejador.
export const $ = (s, node=document) => node.querySelector(s);
export const $$ = (s, node=document) => [...node.querySelectorAll(s)];
export const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const statuses = {not_available:'Não iniciada',available:'Disponível',in_progress:'Em andamento',completed:'Concluída',exempted:'Dispensada',failed:'Reprovada',locked:'Bloqueada'};
export const hours = minutes => minutes == null ? 'Não informada' : `${new Intl.NumberFormat('pt-BR',{maximumFractionDigits:2}).format(minutes/60)} h`;
export const options = selected => Object.entries(statuses).map(([v,l])=>`<option value="${v}" ${v===selected?'selected':''}>${l}</option>`).join('');
export const field = (label,name,value='',type='text',extra='') => `<label class="field">${label}<input name="${name}" type="${type}" value="${esc(value)}" ${extra}></label>`;
export const dialog = $('#editor');
let dirty=false, busy=false, closing=false, toastTimer, returnFocus;
const channel = 'BroadcastChannel' in window ? new BroadcastChannel('plano-formations') : null;
export async function api(path, options={}) {
  const response=await fetch(path,{...options,headers:options.body instanceof FormData?{}:{'Content-Type':'application/json',...options.headers}});
  let data;
  try { data=await response.json(); } catch { throw new Error('O servidor não respondeu corretamente. Tente novamente; seus campos foram mantidos.'); }
  if(!response.ok) {
    const rows=data.details?.rows?.map(r=>`Linha ${r.row}: ${r.errors.join(' ')}`).join('\n');
    throw new Error(rows||data.error||'Não foi possível salvar. Confira os campos e tente novamente.');
  }
  return data;
}
export function notify(message) {clearTimeout(toastTimer);$('#toast').textContent=message;$('#toast').hidden=false;toastTimer=setTimeout(()=>$('#toast').hidden=true,6500);}
export function announce(affected) {
  const event={type:'curriculum-updated',...affected};
  channel?.postMessage(event);window.dispatchEvent(new CustomEvent('plano:data-changed',{detail:event}));
}
export function onUpdated(listener) {channel?.addEventListener('message',e=>{if(e.data?.type==='curriculum-updated')listener(e.data);});}
export function setDirty(value=true) {dirty=value;}
export function openDialog(title,content,step='',wide=false) {
  returnFocus=document.activeElement;dirty=false;
  dialog.classList.toggle('wide',wide);$('#dialog-title').textContent=title;$('#dialog-step').textContent=step;$('#dialog-body').innerHTML=content;
  if(!dialog.open)dialog.showModal();
  ($('#dialog-body input')||$('#dialog-body select')||$('#dialog-close')).focus();
}
export function closeSaved(){dirty=false;dialog.close();returnFocus?.focus();}
export async function closeDialog(){
  if(busy||closing)return;
  if(dirty){
    closing=true;
    const prompt=document.createElement('dialog');prompt.setAttribute('aria-labelledby','discard-title');
    prompt.innerHTML='<div class="dialog-heading"><h2 id="discard-title">Descartar alterações?</h2></div><div class="confirmation-body"><p>Os campos ainda não foram salvos. Você pode continuar editando.</p><div class="form-actions"><button data-answer="keep" autofocus>Continuar editando</button><button data-answer="discard">Descartar alterações</button></div></div>';
    document.body.append(prompt);prompt.showModal();
    const discard=await new Promise(resolve=>{
      const finish=value=>{prompt.close();prompt.remove();resolve(value);};
      prompt.addEventListener('cancel',e=>{e.preventDefault();finish(false);});
      prompt.addEventListener('click',e=>{const answer=e.target.closest('[data-answer]')?.dataset.answer;if(answer)finish(answer==='discard');});
    });
    closing=false;if(!discard)return;
  }
  closeSaved();
}
export function bindSubmit(fn) {
  const form=$('#dialog-body form');
  form.dataset.operationKey=operationKey();
  form.addEventListener('submit',async e=>{
    e.preventDefault();if(busy)return;busy=true;
    const button=$('[type=submit]',form);button.disabled=true;$('.form-error',form).textContent='';
    try{await fn(form);}catch(error){$('.form-error',form).textContent=error.message;}
    finally{busy=false;button.disabled=false;}
  });
}
export const operationKey = () => crypto.randomUUID();

// Um segundo dialog mantém o formulário original intacto ao cancelar a escolha.
export async function chooseCompletion(id) {
  const preview=await api(`/api/curriculum-workspace/${id}/completion`);
  if(!preview.requires_choice)return {completion_targets:[],completion_version:preview.version};
  const prompt=document.createElement('dialog');prompt.setAttribute('aria-labelledby','completion-title');
  prompt.innerHTML=`<div class="dialog-heading"><h2 id="completion-title">Onde concluir esta disciplina?</h2></div><div class="confirmation-body"><p>Você vai registrar <strong>${esc(preview.source.name)}</strong> como concluída em <strong>${esc(preview.source.formation_name)}</strong>. Deseja aproveitar a conclusão em outra formação?</p><div class="destination-list">${preview.destinations.map(r=>`<label class="destination"><input type="checkbox" value="${r.id}" ${r.academic_status==='completed'||r.archived_at||r.formation_archived_at?'disabled':''}><span><strong>${esc(r.formation_name)}</strong><small>${esc(statuses[r.academic_status])}${r.archived_at||r.formation_archived_at?' · arquivada':''}</small></span></label>`).join('')}</div><p class="muted">Isso registra sua decisão de acompanhamento, não um reconhecimento oficial da instituição. Notas e datas acadêmicas não serão copiadas.</p><div class="form-actions"><button data-decision="cancel">Cancelar</button><button data-decision="current">Somente nesta formação</button><button class="primary" data-decision="selected" disabled>Concluir também nas selecionadas</button></div></div>`;
  document.body.append(prompt);prompt.showModal();
  return new Promise(resolve=>{
    const finish=value=>{prompt.close();prompt.remove();resolve(value);};
    prompt.addEventListener('cancel',e=>{e.preventDefault();finish(null);});
    prompt.addEventListener('change',()=>{$('[data-decision=selected]',prompt).disabled=!$('input:checked',prompt);});
    prompt.addEventListener('click',e=>{
      const decision=e.target.closest('[data-decision]')?.dataset.decision;if(!decision)return;
      finish(decision==='cancel'?null:{completion_targets:decision==='selected'?$$('input:checked',prompt).map(n=>Number(n.value)):[],completion_version:preview.version});
    });
  });
}
$('#dialog-close').onclick=closeDialog;
dialog.addEventListener('cancel',e=>{e.preventDefault();closeDialog();});
dialog.addEventListener('input',()=>dirty=true);
dialog.addEventListener('click',e=>{if(e.target.closest('[data-close]'))closeDialog();});
window.addEventListener('beforeunload',e=>{if(dialog.open&&dirty){e.preventDefault();e.returnValue='';}});
