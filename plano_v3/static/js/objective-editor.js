import {$,esc,api,send,duration,dialog,toast} from './api.js';

const STORAGE='plano.objective-draft.v2';
const kinds={subject:'Disciplina',topic:'Conteúdo',project:'Projeto',step:'Etapa de projeto'};
const sourceKey=s=>s?`${s.kind}:${s.id}`:'';
const sourceName=s=>`${kinds[s.kind]}: ${s.name}${s.parent?' · '+s.parent:''}${s.course?' · '+s.course:''}`;
const normalize=text=>text.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();

export class ObjectiveEditor {
  constructor(callbacks) {
    this.callbacks=callbacks;this.draft=null;this.editing=null;this.sources=[];this.operationKey=null;this.loading=false;
    for(const id of ['objective-intention','objective-experience','objective-constraints','objective-json']) $('#'+id).addEventListener('input',()=>this.persist());
    $('#objective-file').addEventListener('change',e=>this.file(e.target.files[0]));
    const drop=$('#objective-drop');
    drop.addEventListener('dragover',e=>{e.preventDefault();drop.classList.add('dragging');});
    drop.addEventListener('dragleave',()=>drop.classList.remove('dragging'));
    drop.addEventListener('drop',e=>{e.preventDefault();drop.classList.remove('dragging');this.file(e.dataTransfer.files[0]);});
  }
  hasDraft(){try{return !!localStorage.getItem(STORAGE);}catch{return false;}}
  resumeBanner(){$('#objective-resume').hidden=!this.hasDraft();}
  async context(){this.sources=(await api('/objectives/context')).sources;}
  allTasks(){return this.draft?.objective.stages.flatMap(s=>s.tasks)||[];}
  lookup(source){return this.sources.find(s=>sourceKey(s)===sourceKey(source));}
  stage(number){document.querySelectorAll('[data-flow]').forEach(el=>el.classList.toggle('active',Number(el.dataset.flow)<=number));}
  persist(){
    if(!this.operationKey)return;
    const value={draft:this.draft,editing:this.editing,operationKey:this.operationKey,intention:$('#objective-intention').value,experience:$('#objective-experience').value,constraints:$('#objective-constraints').value,json:$('#objective-json').value,prompt:$('#objective-prompt').value};
    try{localStorage.setItem(STORAGE,JSON.stringify(value));}catch{$('#objective-save-note').textContent='O navegador não conseguiu guardar o rascunho. Mantenha esta aba aberta até salvar.';}
    this.resumeBanner();
  }
  layout() {
    $('#objective-create-title').textContent=this.editing?'Revisar caminho':'Novo objetivo com IA';
    $('#objective-confirm').textContent=this.editing?'✓ Salvar caminho':'✓ Adicionar objetivo';
    $('#objective-review-panel').hidden=!this.draft;
    $('#objective-ai-fields').hidden=false;
    $('#objective-prompt-panel').hidden=!$('#objective-prompt').value;
    $('#objective-save-note').textContent=this.editing?'As alterações só entram no objetivo ao salvar.':'A proposta só entra nos seus objetivos ao confirmar.';
    this.stage(this.draft?4:$('#objective-prompt').value?2:1);
    if(this.draft)this.render();
  }
  async start() {
    if(this.hasDraft()){await this.resume();toast('Seu rascunho foi recuperado.');return;}
    await this.context();this.draft=null;this.editing=null;this.operationKey=crypto.randomUUID();
    for(const id of ['objective-intention','objective-experience','objective-constraints','objective-json','objective-prompt','objective-file'])$('#'+id).value='';
    $('#objective-file-name').textContent='Até 1 MB · ainda não grava o objetivo';
    this.layout();this.callbacks.show();$('#objective-intention').focus();
  }
  async resume(navigate=true) {
    let saved;
    try{saved=JSON.parse(localStorage.getItem(STORAGE));}catch{throw new Error('O rascunho não pôde ser lido. Descarte-o para iniciar outra proposta.');}
    if(!saved||!saved.operationKey)throw new Error('Não há rascunho disponível.');
    await this.context();this.draft=saved.draft;this.editing=saved.editing;this.operationKey=saved.operationKey;
    for(const [id,key] of [['intention','intention'],['experience','experience'],['constraints','constraints'],['json','json'],['prompt','prompt']])$('#objective-'+id).value=saved[key]||'';
    this.layout();
    if(navigate)this.callbacks.show();
    else {$('#objectives-overview').hidden=true;$('#objective-detail').hidden=true;$('#objective-create').hidden=false;}
  }
  async revise(current) {
    if(this.hasDraft()) {
      dialog('Você tem uma proposta em rascunho','<p>Revisar este objetivo substituirá a proposta ainda não salva. Você também pode cancelar e retomar o rascunho na lista de objetivos.</p>',()=>this.beginRevision(current),'Revisar este objetivo');
      return;
    }
    await this.beginRevision(current);
  }
  async beginRevision(current) {
    await this.context();
    // Read the path and version from the same detail response before preparing edits.
    const fresh=await api('/objectives/'+current.id);
    if(fresh.archived_at)throw new Error('Restaure o objetivo antes de revisar.');
    this.editing={id:fresh.id,version:fresh.version};this.operationKey=crypto.randomUUID();
    this.draft={schema_version:1,objective:{title:fresh.title,description:fresh.description,stages:fresh.stages.map(s=>({key:s.stage_key,title:s.title,description:s.description,tasks:s.tasks.map(t=>({key:t.task_key,title:t.title,description:t.description,planned_minutes:t.planned_minutes,requires:t.requires,source:t.source?{kind:t.source.kind,id:t.source.id}:null}))}))}};
    $('#objective-intention').value=fresh.title+'\n'+fresh.description;
    for(const id of ['objective-experience','objective-constraints','objective-json','objective-prompt','objective-file'])$('#'+id).value='';
    this.layout();this.persist();this.callbacks.show();$('#objective-review-panel').scrollIntoView({block:'start'});
  }
  parse(text) {
    if(new Blob([text]).size>1024*1024)throw new Error('Use uma proposta de até 1 MB.');
    const raw=text.trim().replace(/^```(?:json)?\s*\n([\s\S]*?)\n```$/i,'$1');
    try{return JSON.parse(raw);}catch{throw new Error('Não foi possível ler a proposta. Cole o JSON ou envie o arquivo da IA, sem o restante da conversa.');}
  }
  async preview(text) {
    const operation = this.operationKey;
    const value=this.parse(text);
    const canonical=await send('/objectives/preview',{document:value});
    await this.context();
    if (operation !== this.operationKey) return;
    this.draft=canonical;
    this.render();this.stage(4);this.persist();
    $('#objective-experience').closest('details').open=false;
    $('#objective-review-panel').scrollIntoView({block:'start'});
    $('#objective-review-panel').tabIndex=-1;
    $('#objective-review-panel').focus({preventScroll:true});
  }
  async file(file) {
    if(!file||this.loading)return;
    this.loading=true;
    try {
      if(file.size>1024*1024)throw new Error('Use um arquivo de até 1 MB.');
      const text=await file.text();$('#objective-json').value=text;
      await this.preview(text);$('#objective-file-name').textContent=file.name+' · proposta carregada';
    }catch(e){this.callbacks.fail(e);}finally{this.loading=false;$('#objective-file').value='';}
  }
  render() {
    const obj=this.draft.objective, all=this.allTasks(), linked=all.map(t=>this.lookup(t.source)).filter(Boolean);
    const completed=linked.filter(s=>s.status==='completed').length;
    const open=new Set([...document.querySelectorAll('.objective-draft-stage[open]')].map(s=>s.dataset.key));
    $('#objective-draft-summary').innerHTML=`<section><small>◎ Objetivo</small><strong>${esc(obj.title)}</strong><p class="small-note muted">${esc(obj.description)}</p></section><section><small>Estimativa total</small><strong class="estimate">≈ ${duration(all.reduce((n,t)=>n+t.planned_minutes*60,0))}</strong><small>${obj.stages.length} etapas · ${all.length} afazeres</small></section><section><small>Vínculos reconhecidos</small>${linked.length?linked.map(s=>`<span class="source-chip">${esc(s.name)}</span>`).join(''):'<span>Caminho independente</span>'}${completed?`<small>${completed} afazer(es) já concluído(s) na origem.</small>`:''}</section>`;
    $('#objective-draft-stages').innerHTML=obj.stages.map((s,index)=>`<details class="objective-draft-stage" data-key="${esc(s.key)}" ${open.has(s.key)?'open':''}><summary><span class="objective-stage-number">${index+1}</span><div><strong>${esc(s.title)}</strong><small>${esc(s.description)}</small></div><span>${s.tasks.length} afazeres · ${duration(s.tasks.reduce((n,t)=>n+t.planned_minutes*60,0))}</span></summary>${s.tasks.map(t=>{
      const source=this.lookup(t.source);
      return `<div class="objective-draft-task"><button data-action="draft-task" data-key="${esc(t.key)}"><strong>${esc(t.title)}</strong><small>${source?esc(sourceName(source)):'Afazer independente'}${source?.status==='completed'?' · ✓ Concluído':''}${t.requires.length?` · ${t.requires.length} requisito(s)`:''}</small></button><span>${duration(t.planned_minutes*60)} · ✎</span></div>`;
    }).join('')}<div class="objective-draft-actions"><button class="text-button" data-action="add-task" data-stage-key="${esc(s.key)}">＋ Adicionar afazer</button><button class="text-button" data-action="edit-stage" data-stage-key="${esc(s.key)}">Editar etapa</button><button class="text-button" data-action="remove-stage" data-stage-key="${esc(s.key)}">Remover etapa</button></div></details>`).join('');
    $('#objective-review-panel').hidden=false;
    $('#objective-draft-error').textContent='';
  }
  changed(){this.render();this.persist();}
  metadata() {
    const obj=this.draft.objective;
    dialog('Editar proposta',`<label>Objetivo<input name="title" value="${esc(obj.title)}" maxlength="200" required></label><label>Resultado esperado<textarea name="description" maxlength="5000">${esc(obj.description)}</textarea></label>`,values=>{Object.assign(obj,values);this.changed();});
  }
  editStage(stage=null) {
    dialog(stage?'Editar etapa':'Nova etapa',`<label>Etapa<input name="title" maxlength="200" required value="${esc(stage?.title||'')}"></label><label>Descrição<textarea name="description" maxlength="2000">${esc(stage?.description||'')}</textarea></label>`,values=>{
      if(stage)Object.assign(stage,values);
      else this.draft.objective.stages.push({key:'stage_'+crypto.randomUUID(),...values,tasks:[]});
      this.changed();
    });
  }
  editTask(task=null,stage=null) {
    const value=task||{key:'task_'+crypto.randomUUID(),title:'',description:'',planned_minutes:60,source:null,requires:[]};
    const others=this.allTasks().filter(t=>t.key!==value.key), used=new Set(others.map(t=>sourceKey(t.source)).filter(Boolean));
    let selectedSource=sourceKey(value.source);
    const el=dialog(task?'Ajustar afazer':'Novo afazer',`<label>Afazer<input name="title" maxlength="200" required value="${esc(value.title)}"></label><label>O que precisa ser feito?<textarea name="description" maxlength="5000">${esc(value.description)}</textarea></label><label>Tempo previsto (minutos)<input type="number" name="planned_minutes" min="1" max="600000" step="1" required value="${value.planned_minutes}"></label><details ${value.source?'open':''}><summary>Vincular a um estudo existente ${value.source?'· vínculo selecionado':'· opcional'}</summary><label>Buscar disciplina, conteúdo ou projeto<input type="search" data-source-search placeholder="Digite parte do nome"></label><div class="objective-picker" data-sources></div></details><details ${value.requires.length?'open':''}><summary>Pré-requisitos · ${value.requires.length} selecionado(s)</summary><div class="objective-picker">${others.length?others.map(t=>`<label><input type="checkbox" data-requires value="${esc(t.key)}" ${value.requires.includes(t.key)?'checked':''}>${esc(t.title)}</label>`).join(''):'Ainda não há outros afazeres.'}</div></details>${task?'<button type="button" class="text-button" data-remove-task>Remover este afazer da proposta</button>':''}`,async values=>{
      const next={...value,title:values.title,description:values.description,planned_minutes:Number(values.planned_minutes),requires:[...el.querySelectorAll('[data-requires]:checked')].map(x=>x.value),source:selectedSource?{kind:selectedSource.split(':')[0],id:Number(selectedSource.split(':')[1])}:null};
      // Validate the entire proposed path before replacing an existing item.
      const copy=structuredClone(this.draft);
      if(task){const target=copy.objective.stages.flatMap(s=>s.tasks).find(t=>t.key===task.key);Object.assign(target,next);}
      else copy.objective.stages.find(s=>s.key===stage.key).tasks.push(next);
      // New empty stages may be completed later; the final save always validates the full path.
      if(copy.objective.stages.every(s=>s.tasks.length))await send('/objectives/preview',{document:copy});
      if(task)Object.assign(task,next);else stage.tasks.push(next);
      this.changed();
    },'Aplicar na proposta');
    const drawSources=()=>{
      const query=normalize($('[data-source-search]',el).value);
      const available=this.sources.filter(s=>(!s.archived||sourceKey(s)===selectedSource)&&!used.has(sourceKey(s))&&(!query||normalize(sourceName(s)).includes(query)||sourceKey(s)===selectedSource));
      $('[data-sources]',el).innerHTML=`<label><input type="radio" name="source_ref" value="" ${!selectedSource?'checked':''}> Sem vínculo · afazer independente</label>`+available.map(s=>`<label><input type="radio" name="source_ref" value="${sourceKey(s)}" ${sourceKey(s)===selectedSource?'checked':''}>${esc(sourceName(s))}${s.status==='completed'?' · ✓ Concluído':''}</label>`).join('');
    };
    $('[data-source-search]',el).oninput=drawSources;
    $('[data-sources]',el).onchange=e=>{if(e.target.name==='source_ref')selectedSource=e.target.value;};
    $('[data-remove-task]',el)?.addEventListener('click',()=>{
      el.close();this.removeTask(task);
    });
    drawSources();
  }
  removeTask(task) {
    dialog('Remover afazer da proposta',`<p>${esc(task.title)}</p><p>Ele também será removido dos pré-requisitos de outros afazeres. Seus estudos vinculados permanecem intactos.</p>`,()=>{
      for(const stage of this.draft.objective.stages)stage.tasks=stage.tasks.filter(t=>t.key!==task.key);
      for(const t of this.allTasks())t.requires=t.requires.filter(k=>k!==task.key);
      this.changed();
    },'Remover da proposta');
  }
  async prompt() {
    const intention=$('#objective-intention').value.trim();
    if(!intention)throw new Error('Descreva o que você quer alcançar.');
    await this.context();
    const context=this.sources.filter(s=>!s.archived).map(({kind,id,name,parent,course,status,needs_review})=>({kind,id,name,parent,...(course?{course}:{}),status,needs_review}));
    const example={schema_version:1,objective:{title:'Título específico do resultado',description:'O que estará pronto e como verificar.',stages:[{key:'definir',title:'Definir o resultado',description:'Delimitar o problema e os critérios de sucesso.',tasks:[{key:'criterios',title:'Definir critérios verificáveis',description:'Listar os comportamentos esperados.',planned_minutes:60,source:null,requires:[]}]}]}};
    $('#objective-prompt').value=`Quero estruturar este objetivo:\n${intention}\n\nO que já sei:\n${$('#objective-experience').value.trim()||'Pergunte se for necessário.'}\n\nTempo disponível e condições:\n${$('#objective-constraints').value.trim()||'Pergunte se for necessário; não imponha calendário.'}\n\nConverse comigo antes de fechar o caminho: confirme o resultado concreto, os requisitos que faltam e como vou verificar que consegui. Depois organize etapas específicas do objetivo e afazeres claros, com descrição, estimativa de minutos e pré-requisitos. Evite etapas vagas como apenas "fundamentos". Não transforme o objetivo numa grade inteira se isso não for necessário. Não acrescente testes, aulas ou vídeos obrigatórios: este site acompanha meu progresso.\n\nMeus estudos atuais (use os identificadores reais apenas quando houver correspondência):\n${JSON.stringify(context)}\n\nVincule um afazer à disciplina, conteúdo, projeto ou etapa existente quando eles representarem o MESMO trabalho. Assim a conclusão será acompanhada automaticamente. Para uma aplicação nova do conhecimento, prefira um afazer independente com requisito, evitando declará-la concluída só porque a disciplina terminou. Use source:null quando não houver correspondência.\n\n${this.editing?'Estou revisando um caminho existente. Preserve as keys dos afazeres que continuarem representando o mesmo trabalho para conservar meu progresso. Caminho atual:\n'+JSON.stringify(this.draft)+'\n\n':''}Quando eu aprovar a proposta, entregue um arquivo JSON neste formato:\n${JSON.stringify(example,null,2)}\n\nRegras do arquivo: schema_version=1; até 30 etapas e 200 afazeres; cada etapa deve conter afazeres. Keys únicas de até 60 caracteres, apenas letras, números, hífen ou sublinhado. planned_minutes inteiro entre 1 e 600000. requires é uma lista de keys de afazeres do objetivo, sem ciclos. source é null ou {"kind":"subject|topic|project|step","id":ID_REAL}. Não repita o mesmo vínculo em dois afazeres. Não gere status, needs_review nem horas realizadas: o site consulta a origem. Substitua os exemplos pelo caminho que combinamos.`;
    $('#objective-prompt-panel').hidden=false;this.stage(2);this.persist();$('#objective-prompt-panel').scrollIntoView({block:'start'});
  }
  async action(action,button) {
    if(action==='resume')return this.resume();
    if(action==='discard-draft')return dialog('Descartar rascunho','<p>Apenas a proposta não salva será removida. Seus objetivos cadastrados permanecem intactos.</p>',()=>{localStorage.removeItem(STORAGE);this.draft=null;this.operationKey=null;this.resumeBanner();},'Descartar rascunho');
    if(action==='prompt')return this.prompt();
    if(action==='copy'){
      try{await navigator.clipboard.writeText($('#objective-prompt').value);toast('Texto copiado. Cole na IA que preferir.');}
      catch{$('#objective-prompt').focus();$('#objective-prompt').select();toast('Use Ctrl+C para copiar o texto selecionado.');}
    }
    if(action==='preview')return this.preview($('#objective-json').value);
    if(action==='draft-metadata')return this.metadata();
    if(action==='draft-task')return this.editTask(this.allTasks().find(t=>t.key===button.dataset.key));
    if(action==='add-stage')return this.editStage();
    if(action==='edit-stage')return this.editStage(this.draft.objective.stages.find(s=>s.key===button.dataset.stageKey));
    if(action==='add-task')return this.editTask(null,this.draft.objective.stages.find(s=>s.key===button.dataset.stageKey));
    if(action==='remove-stage'){
      const stage=this.draft.objective.stages.find(s=>s.key===button.dataset.stageKey);
      return dialog('Remover etapa da proposta',`<p>${esc(stage.title)} · ${stage.tasks.length} afazeres.</p><p>Os vínculos e sessões de estudo originais permanecem intactos.</p>`,()=>{
        const keys=new Set(stage.tasks.map(t=>t.key));this.draft.objective.stages=this.draft.objective.stages.filter(s=>s.key!==stage.key);
        for(const t of this.allTasks())t.requires=t.requires.filter(k=>!keys.has(k));this.changed();
      },'Remover da proposta');
    }
    if(action==='confirm'){
      if(this.loading)throw new Error('Aguarde a leitura do arquivo.');
      $('#objective-confirm').disabled=true;
      try{
        const canonical=await send('/objectives/preview',{document:this.draft});
        const saved=this.editing?await send(`/objectives/${this.editing.id}/path`,{version:this.editing.version,document:canonical},'PUT'):await send('/objectives',{operation_key:this.operationKey,document:canonical});
        localStorage.removeItem(STORAGE);this.draft=null;this.operationKey=null;this.editing=null;
        await this.callbacks.saved(saved);
      }catch(e){$('#objective-draft-error').textContent=e.message;$('#objective-draft-error').scrollIntoView({block:'nearest'});}
      finally{$('#objective-confirm').disabled=false;}
    }
  }
}
