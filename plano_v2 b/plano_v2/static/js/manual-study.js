import {$,$$,esc,api,notify,announce,onUpdated,openDialog,bindSubmit,closeSaved,dialog,operationKey} from './workspace-ui.js';

const root='/api/manual-study';
const normalize=v=>String(v||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
const duration=total=>{const s=Math.max(0,Math.floor(total||0));return `${String(Math.floor(s/3600)).padStart(2,'0')}:${String(Math.floor(s/60)%60).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;};
const reasons={'':'Sem motivo informado',rest:'Descanso',water_food:'Água / alimentação',bathroom:'Banheiro',external_interruption:'Interrupção',difficulty:'Dificuldade',other:'Outro'};
const reasonOptions=()=>Object.entries(reasons).map(([v,l])=>`<option value="${v}">${l}</option>`).join('');
const footer=label=>`<p class="form-error" role="alert"></p><div class="form-actions"><button type="button" data-close>Cancelar</button><button class="primary" type="submit">${label}</button></div>`;
let catalog=[],focus=null,received=0,day,choiceToken=0,requestToken=0,notes=null,noteTimer,noteSaving=null,busy=false,startAttempt=null;
let tabId=sessionStorage.getItem('manual-tab');if(!tabId){tabId=operationKey();sessionStorage.setItem('manual-tab',tabId);}
const requested=new URLSearchParams(location.search);
const noteKey=id=>`plano:manual-note:${id}:${tabId}`;
const changed=()=>{const event={curriculum_ids:catalog.flatMap(r=>r.contexts.map(c=>c.id)),formation_ids:catalog.flatMap(r=>r.contexts.map(c=>c.formation_id))};announce(event);};
async function mutate(path,values={},method='POST',key=operationKey()){return api(root+path,{method,body:JSON.stringify({operation_key:key,...values})});}
function fail(error){$('#study-error').hidden=false;$('#study-error span').textContent=error.message;}
function draftSave(){try{localStorage.setItem(noteKey(notes.id),JSON.stringify({...notes,at:Date.now()}));}catch{notify('Não foi possível guardar o rascunho local. Mantenha esta aba aberta até salvar.');}}
function draftClear(){try{localStorage.removeItem(noteKey(notes.id));if(notes.recoveredKey)localStorage.removeItem(notes.recoveredKey);}catch{}}
function noteStatus(message){$('#note-state')?.replaceChildren(document.createTextNode(message));}

function initNotes(f){
  if(notes?.id===f.id){if(!notes.dirty&&!noteSaving){notes.text=f.note?.content_markdown||'';notes.revision=f.note_revision;}return;}
  notes={id:f.id,text:f.note?.content_markdown||'',revision:f.note_revision,dirty:false};
  try{
    const saved=Object.keys(localStorage).filter(k=>k.startsWith(`plano:manual-note:${f.id}:`)).map(k=>({key:k,...JSON.parse(localStorage.getItem(k))})).sort((a,b)=>b.at-a.at);
    const draft=saved.find(r=>r.key===noteKey(f.id))||saved[0];
    if(draft&&draft.text!==notes.text)notes={...notes,text:draft.text,revision:draft.revision,dirty:true,recoveredKey:draft.key};
  }catch{}
}
async function saveNote(){
  if(!notes?.dirty)return true;
  if(noteSaving){await noteSaving;return notes.dirty?saveNote():true;}
  const captured={id:notes.id,text:notes.text,revision:notes.revision};
  noteStatus('Salvando…');
  noteSaving=(async()=>{
    try{
      const result=await mutate(`/focus/${captured.id}/note`,{text:captured.text,revision:captured.revision},'PUT');
      if(notes.id===captured.id){
        notes.revision=result.revision;notes.dirty=notes.text!==captured.text;notes.error=false;
        if(notes.dirty){draftSave();noteStatus('Alterações aguardando salvamento…');}
        else{draftClear();noteStatus('Salvo');}
      }
      return true;
    }catch(error){notes.error=true;draftSave();noteStatus(error.message+' Use Tentar salvar ou compare com a versão salva.');return false;}
  })();
  const ok=await noteSaving;noteSaving=null;
  if(ok&&notes.dirty){clearTimeout(noteTimer);noteTimer=setTimeout(saveNote,650);}
  return ok;
}

function showSubjects(){
  const selected=$('#study-subject').value;
  const q=normalize($('#study-search').value);
  const items=catalog.filter(r=>normalize(r.name+' '+r.contexts.map(c=>c.formation_name).join(' ')).includes(q));
  $('#study-subject').innerHTML='<option value="">Escolha uma matéria</option>'+items.map(r=>`<option value="${esc(r.key)}">${esc(r.name)}${r.shared?' · compartilhada':''}</option>`).join('');
  if(items.some(r=>r.key===selected))$('#study-subject').value=selected;
  if(!$('#study-subject').value){$('#study-context').innerHTML='';$('#study-topic').innerHTML='<option value="">Sem tópico</option>';}
}
function selectedValues(){
  const item=catalog.find(r=>r.key===$('#study-subject').value);
  if(!item)throw new Error('Escolha uma matéria.');
  return item.curriculum_id?{curriculum_id:Number($('#study-context').value)}:{study_id:item.study_id};
}
async function updateChoice(newSubject=false){
  const token=++choiceToken;
  const item=catalog.find(r=>r.key===$('#study-subject').value);
  if(!item)return;
  if(newSubject){
    $('#study-context').innerHTML=item.contexts.map(c=>`<option value="${c.id}">${esc(c.formation_name)}</option>`).join('')||'<option>Estudo pessoal</option>';
    $('#study-context').disabled=!item.contexts.length;
    if(requested.get('curriculum')&&item.contexts.some(c=>String(c.id)===requested.get('curriculum')))$('#study-context').value=requested.get('curriculum');
  }
  $('#start-button').disabled=true;
  try{
    const data=await api(root+'/choices?'+new URLSearchParams(selectedValues()));
    if(token!==choiceToken)return;
    $('#study-topic').innerHTML='<option value="">Sem tópico</option>'+data.topics.map(t=>`<option value="${t.id}">${esc(t.name)}${t.read_only?' · referência preservada':''}</option>`).join('');
    $('#study-purpose').value=data.purpose;
  }catch(error){fail(error);}finally{if(token===choiceToken)$('#start-button').disabled=false;}
}

function renderFocus(f){
  const previous=focus;focus=f;received=performance.now();
  const panel=$('#current-focus');panel.hidden=!f;
  $('#study-choice').hidden=!!f&&['running','paused','recovery_required','finishing'].includes(f.status);
  if(!f){panel.innerHTML='';return;}
  initNotes(f);
  if(previous?.id===f.id&&previous.status===f.status&&panel.querySelector('#clock-value')){
    if(!notes.dirty&&!noteSaving&&document.activeElement!==$('#focus-note'))$('#focus-note').value=notes.text;
    tick();return;
  }
  const closed=f.status==='completed',active=['running','paused','recovery_required'].includes(f.status);
  panel.innerHTML=`<div class="section-heading"><div><span class="eyebrow">${closed?'✓ SESSÃO CONCLUÍDA':f.purpose==='review'?'REVISÃO MANUAL':'SESSÃO MANUAL'}</span><h2>${esc(f.subject_name)}</h2><p>${esc(f.topic_name||'Sem tópico')} · ${closed?'Registro salvo':f.status==='paused'?'Pausado':f.status==='recovery_required'?'Revisar sessão antiga':'Estudando'}</p></div>${f.context_id?`<a href="/curriculum/${f.context_id}?return=%2Ftoday">Ver disciplina →</a>`:''}</div>
    <div class="focus-layout"><div class="manual-clock" id="clock-face" role="img" style="--subject-color:${f.color}"><div class="manual-clock-inner"><small>Tempo efetivo</small><strong id="clock-value"></strong><small id="clock-hours"></small><small>Uma volta = 60 minutos</small></div></div>
    <div><p id="clock-target"></p><div class="focus-stats"><div><span>Em pausa</span><strong id="clock-paused"></strong></div><div><span>Tempo decorrido</span><strong id="clock-wall"></strong></div></div>
    <p id="clock-warning" class="notice" ${f.review_required?'':'hidden'}>Sessão longa: confira o horário de encerramento antes de salvar.</p>
    <div class="focus-controls">${active?`${f.status==='running'?'<button id="pause-focus">Pausar</button>':f.status==='paused'?'<button id="resume-focus" class="primary">Retomar</button>':''}<button id="finish-focus">Encerrar</button>`:closed?`<strong class="manual-completed">✓ Tempo salvo</strong><button id="feedback-focus">Adicionar resultado (opcional)</button><a href="/today">Escolher outro estudo →</a>`:''}</div>
    <details><summary>Pausas registradas (${f.breaks.length})</summary>${f.breaks.map(p=>`<p>${esc(reasons[p.reason||''])} · ${p.duration_seconds==null?'Em andamento':duration(p.duration_seconds)}</p>`).join('')||'<p>Nenhuma pausa registrada.</p>'}</details></div></div>
    <label class="field">Anotações da sessão<textarea class="manual-note" id="focus-note" ${f.status==='cancelled'?'disabled':''}>${esc(notes.text)}</textarea></label><p id="note-state" class="manual-note-status" role="status">${notes.dirty?'Rascunho local recuperado — confira e salve.':'Salvo'}</p>
    <div class="row-actions"><button id="retry-note">Tentar salvar</button><button id="compare-note">Comparar com versão salva</button></div>`;
  $('#focus-note').addEventListener('input',e=>{notes.text=e.target.value;notes.dirty=true;draftSave();noteStatus('Alterações aguardando salvamento…');clearTimeout(noteTimer);noteTimer=setTimeout(saveNote,650);});
  $('#retry-note').onclick=saveNote;
  $('#compare-note').onclick=compareNote;
  $('#pause-focus')?.addEventListener('click',pauseDialog);
  $('#resume-focus')?.addEventListener('click',()=>control('resume'));
  $('#finish-focus')?.addEventListener('click',finishDialog);
  $('#feedback-focus')?.addEventListener('click',()=>feedbackDialog(f.result.id));
  tick();
}
function tick(){
  if(!focus||!$('#clock-value'))return;
  const delta=Math.max(0,(performance.now()-received)/1000);
  const closed=focus.status==='completed';
  const effective=closed?focus.result.duration_seconds:focus.elapsed_seconds+(focus.status==='running'?delta:0);
  const paused=closed?focus.result.pause_seconds:focus.pause_seconds+(focus.status==='paused'?delta:0);
  const wall=closed?effective+paused:focus.wall_seconds+(['running','paused'].includes(focus.status)?delta:0);
  $('#clock-value').textContent=duration(effective);$('#clock-paused').textContent=duration(paused);$('#clock-wall').textContent=duration(wall);
  $('#clock-face').style.setProperty('--angle',`${effective%3600/3600*360}deg`);
  $('#clock-face').setAttribute('aria-label',`${duration(effective)} de estudo efetivo. Uma volta corresponde a uma hora.`);
  $('#clock-hours').textContent=`${Math.floor(effective/3600)} hora(s) completa(s)`;
  $('#clock-warning').hidden=closed||wall<8*3600;
  const target=focus.target_seconds;
  $('#clock-target').textContent=target?`Duração escolhida: ${duration(target)} · ${effective>=target?'Duração alcançada; continue ou encerre quando quiser.':'Faltam '+duration(target-effective)+' efetivos.'}`:'Cronômetro livre — encerre quando quiser.';
  if(!closed&&target&&effective>=target&&!sessionStorage.getItem('target-noticed:'+focus.id)){sessionStorage.setItem('target-noticed:'+focus.id,'1');notify('Duração escolhida alcançada. O cronômetro continua até você encerrar.');}
}
async function control(action,values={}){
  if(busy)return;busy=true;
  try{await mutate(`/focus/${focus.id}/${action}`,{version:focus.version,...values});changed();await refresh();}
  catch(error){notify(error.message);await refresh();}
  finally{busy=false;}
}
function pauseDialog(){
  openDialog('Pausar estudo',`<form><label class="field">Motivo (opcional)<select name="reason">${reasonOptions()}</select></label>${footer('Pausar agora')}</form>`);
  bindSubmit(async form=>{await mutate(`/focus/${focus.id}/pause`,{version:focus.version,reason:new FormData(form).get('reason')});closeSaved();changed();await refresh();});
}
async function finishDialog(){
  await saveNote();
  const latest=await api(root+`/focus/${focus.id}`);renderFocus(latest);
  if(latest.status==='completed')return;
  const dateValue=latest.server_now.slice(0,19);
  openDialog('Encerrar estudo',`<form><p>O tempo efetivo será salvo agora. Comentário, resultado e domínio podem ser informados depois.</p>${latest.review_required?`<p class="notice">Esta sessão ficou aberta por muitas horas. Confira o período registrado.</p><p>Início: ${esc(latest.started_at.replace('T',' '))}</p><label class="field">Encerramento real (São Paulo)<input type="datetime-local" step="1" name="reviewed_end_at" value="${dateValue}" required></label>${!latest.manual_mode?`<label class="field">Tempo efetivo real em horas<input type="number" name="actual_hours" min="0.0003" step="any" value="${latest.elapsed_seconds/3600}" required></label>`:''}<label><input type="checkbox" name="review_confirmed" required> Conferi os horários; pode registrar este período.</label>`:''}${notes?.dirty?'<p class="notice">Sua anotação ainda está no rascunho local. O tempo será salvo e você poderá tentar salvar a anotação novamente.</p>':''}${footer('Salvar tempo e encerrar')}</form>`);
  bindSubmit(async form=>{
    const values=Object.fromEntries(new FormData(form));values.version=latest.version;
    if(values.review_confirmed)values.review_confirmed=true;
    if(values.actual_hours)values.actual_seconds=Math.round(Number(values.actual_hours)*3600);
    const result=await mutate(`/focus/${latest.id}/finish`,values,'POST',form.dataset.operationKey);
    closeSaved();requested.set('session',result.id);history.replaceState(null,'',`/focus?session=${result.id}`);renderFocus(result);changed();await refresh();notify('Sessão salva. Resultado e domínio são opcionais.');
  });
}
async function compareNote(){
  const remote=await api(root+`/focus/${focus.id}`);
  openDialog('Conferir anotações',`<form><p>Seu rascunho local permanece guardado até você decidir.</p><label class="field">Versão salva no banco<textarea readonly>${esc(remote.note?.content_markdown||'')}</textarea></label><label class="field">Seu rascunho<textarea readonly>${esc(notes.text)}</textarea></label><button type="button" id="use-saved-note">Usar versão salva</button>${footer('Salvar meu rascunho sobre esta versão')}</form>`);
  $('#use-saved-note').onclick=()=>{draftClear();notes={id:remote.id,text:remote.note?.content_markdown||'',revision:remote.note_revision,dirty:false};closeSaved();focus=null;renderFocus(remote);};
  bindSubmit(async()=>{notes.revision=remote.note_revision;notes.dirty=true;if(!await saveNote())throw new Error('A anotação mudou novamente. Reabra a comparação.');closeSaved();});
}

function renderDay(){
  $('#today-date').textContent=day.date.split('-').reverse().join('/');
  $('#day-summary').innerHTML=`<div><span>Estudo efetivo salvo hoje</span><strong>${duration(day.total_seconds)}</strong></div><div><span>Pausas registradas hoje</span><strong>${duration(day.pause_seconds)}</strong></div><div><span>Sessões encerradas</span><strong>${day.sessions.length}</strong></div>`;
  $('#today-sessions').innerHTML=day.sessions.map(s=>`<article class="manual-session" style="--subject-color:${s.color}"><div class="section-heading"><h3>${esc(s.subject_name)}</h3><span class="manual-completed">✓ Concluída</span></div><p>${esc(s.topic_name||'Sem tópico')} · ${s.entry_method==='manual'?'Registro manual':'Cronometrada'}${s.purpose==='review'?' · Revisão':''}</p><p>Efetivo hoje: ${duration(s.today_focus_seconds)} · Pausas hoje: ${duration(s.today_pause_seconds)}</p><p class="small-note">${s.started_at?`${esc(s.started_at.replace('T',' '))} → ${esc(s.ended_at?.replace('T',' ')||'')}`:'Horários não informados; somente duração.'}</p>${s.notes?`<p class="preserve-lines">${esc(s.notes)}</p>`:''}<div class="row-actions"><button data-result="${s.id}">Ver registro / resultado</button></div></article>`).join('')||'<p class="empty">Nenhuma sessão encerrada hoje. Você pode começar um estudo ou registrar um que já realizou.</p>';
}
async function refresh(){
  const token=++requestToken;
  const result=await api(root+'/today');
  if(token!==requestToken)return;
  day=result;$('#study-error').hidden=true;renderDay();
  let shown=result.active;
  if(!shown&&requested.get('session'))shown=await api(root+`/focus/${Number(requested.get('session'))}`);
  else if(!shown&&focus?.status==='completed')shown=focus;
  renderFocus(shown);
}

async function manualDialog(){
  openDialog('Registrar estudo realizado',`<form><div class="form-grid"><label class="field full">Matéria<select name="subject" required><option value="">Escolha</option>${catalog.flatMap(r=>r.contexts.length?r.contexts.map(c=>`<option value="curriculum:${c.id}">${esc(r.name)} · ${esc(c.formation_name)}</option>`):[`<option value="study:${r.study_id}">${esc(r.name)}</option>`]).join('')}</select></label><label class="field">Data<input type="date" name="date" max="${day.date}" value="${day.date}" required></label><label class="field">Duração efetiva em horas<input type="number" name="hours" min="0.01" max="24" step="0.01" required placeholder="Ex.: 1,5"></label><label class="field">Tópico (opcional)<select name="topic_id"><option value="">Sem tópico</option></select></label><label class="field">Finalidade<select name="purpose"><option value="study">Estudo</option><option value="review">Revisão</option></select></label></div><p>Informe somente o tempo estudado. As pausas abaixo são adicionais, não são descontadas novamente.</p><div id="manual-pauses"></div><button type="button" id="add-manual-pause">Adicionar pausa (opcional)</button><label class="field">Comentário (opcional)<textarea name="notes"></textarea></label>${footer('Salvar registro manual')}</form>`);
  const form=$('#dialog-body form');let revision=0;
  form.elements.subject.onchange=async()=>{const token=++revision;const [kind,id]=form.elements.subject.value.split(':');if(!id)return;try{const data=await api(root+'/choices?'+new URLSearchParams({[kind==='curriculum'?'curriculum_id':'study_id']:id}));if(token!==revision)return;form.elements.topic_id.innerHTML='<option value="">Sem tópico</option>'+data.topics.map(t=>`<option value="${t.id}">${esc(t.name)}</option>`).join('');form.elements.purpose.value=data.purpose;}catch(error){$('.form-error',form).textContent=error.message;}};
  $('#add-manual-pause').onclick=()=>{const row=document.createElement('div');row.className='pause-entry';row.innerHTML=`<label class="field">Horas de pausa<input type="number" data-hours min="0.01" max="24" step="0.01" required></label><label class="field">Motivo<select data-reason>${reasonOptions()}</select></label><button type="button">Remover pausa</button>`;row.querySelector('button').onclick=()=>row.remove();$('#manual-pauses').append(row);};
  bindSubmit(async form=>{const values=Object.fromEntries(new FormData(form));const [kind,id]=values.subject.split(':');values[kind==='curriculum'?'curriculum_id':'study_id']=Number(id);delete values.subject;values.duration_seconds=Math.round(Number(values.hours)*3600);values.pauses=$$('.pause-entry',form).map(r=>({duration_seconds:Math.round(Number($('[data-hours]',r).value)*3600),reason:$('[data-reason]',r).value}));await mutate('/sessions',values,'POST',form.dataset.operationKey);closeSaved();changed();await refresh();notify('Registro manual salvo.');});
}
async function feedbackDialog(id){
  const s=await api(root+`/sessions/${id}`);
  const opts='<option value="">Não alterar</option>'+[1,2,3,4,5].map(v=>`<option value="${v}">${v}</option>`).join('');
  openDialog('Registro salvo · resultado opcional',`<form><p><strong>${esc(s.subject_name)}</strong> · ${duration(s.duration_seconds)} efetivos · ${duration(s.pause_seconds)} em pausas</p><p>${s.entry_method==='manual'?'Registro manual':'Cronometrada'} · ${s.purpose==='review'?'Revisão':'Estudo'}</p>${s.annotations.map(n=>`<details><summary>${esc(n.title)}</summary><p class="preserve-lines">${esc(n.content_markdown)}</p></details>`).join('')}<label class="field">Comentário (opcional)<textarea name="notes">${esc(s.notes||'')}</textarea></label>${s.topic_id&&s.context_id?`<label class="field">Situação do tópico<select name="topic_status"><option value="">Não alterar</option><option value="not_started">Não iniciado</option><option value="in_progress">Em andamento</option><option value="completed">Concluído</option></select></label><label class="field">Domínio do tópico (opcional)<select name="topic_mastery">${opts}</select></label>`:''}${s.context_id?`<label class="field">Domínio da matéria (opcional)<select name="mastery">${opts}</select></label>`:''}<p class="small-note">Nada será concluído ou avaliado automaticamente. O tempo já está salvo.</p>${footer('Salvar resultado')}</form>`);
  bindSubmit(async form=>{const values=Object.fromEntries(new FormData(form));for(const key of ['mastery','topic_mastery'])if(!values[key])delete values[key];values.version=s.version;await mutate(`/sessions/${id}/feedback`,values,'POST',form.dataset.operationKey);closeSaved();changed();await refresh();notify('Resultado salvo.');});
}

$('#study-search').oninput=showSubjects;
$('#study-subject').onchange=()=>updateChoice(true);
$('#study-context').onchange=()=>updateChoice();
$('#study-mode').onchange=()=>{$('#target-field').hidden=$('#study-mode').value!=='target';$('#study-target').required=!$('#target-field').hidden;};
$('#start-study').onsubmit=async e=>{
  e.preventDefault();if(busy)return;busy=true;$('#start-button').disabled=true;
  try{const values={...selectedValues(),topic_id:$('#study-topic').value||null,purpose:$('#study-purpose').value,target_seconds:$('#study-mode').value==='target'?Math.round(Number($('#study-target').value)*3600):null};const signature=JSON.stringify(values);if(startAttempt?.signature!==signature)startAttempt={signature,key:operationKey()};const result=await mutate('/focus',values,'POST',startAttempt.key);changed();location.href=`/focus?session=${result.id}`;}
  catch(error){$('#start-study .form-error').textContent=error.message;await refresh();}
  finally{busy=false;$('#start-button').disabled=false;}
};
$('#manual-record').onclick=()=>manualDialog().catch(fail);
$('#today-sessions').onclick=e=>{const id=e.target.closest('[data-result]')?.dataset.result;if(id)feedbackDialog(id).catch(fail);};
$('#study-retry').onclick=()=>boot().catch(fail);
onUpdated(()=>{if(!dialog.open)refresh().catch(fail);});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh().catch(fail);});
window.addEventListener('online',()=>{saveNote();refresh().catch(fail);});
window.addEventListener('beforeunload',e=>{if(notes?.dirty){draftSave();e.preventDefault();e.returnValue='';}});
setInterval(tick,1000);
setInterval(async()=>{if(document.hidden||busy||dialog.open)return;try{const current=await api(root+'/focus/active');if(current)renderFocus(current);else if(focus&&focus.status!=='completed')await refresh();}catch(error){fail(error);}},8000);
async function boot(){const loaded=await api(root+'/catalog');catalog=loaded.items;showSubjects();const item=catalog.find(r=>r.contexts.some(c=>String(c.id)===requested.get('curriculum'))||String(r.study_id)===requested.get('study'));if(item){$('#study-subject').value=item.key;await updateChoice(true);}await refresh();}
boot().catch(fail);
