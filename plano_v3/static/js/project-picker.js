import {$,esc,api} from './api.js';
export function projectPicker(root,{archived=false}={}){
  root.innerHTML='<label>Projeto<select data-project required><option value="">Selecione um projeto</option></select></label><label>Etapa (opcional)<select data-step><option value="">Sem etapa informada</option></select></label><p class="field-help"><a href="/projects">Gerenciar projetos e etapas →</a></p><p data-project-error class="form-error" role="alert"></p>';
  const project=$('[data-project]',root),step=$('[data-step]',root),error=$('[data-project-error]',root);
  let sequence=0,catalogSequence=0,loading=false,failed=false;
  async function steps(selected=''){
    const run=++sequence;loading=true;failed=false;step.disabled=true;error.textContent='';
    step.innerHTML='<option value="">Sem etapa informada</option>';
    try{
      if(project.value){
        const p=await api('/projects/'+project.value);if(run!==sequence)return;
        step.innerHTML+=p.steps.map(s=>`<option value="${s.id}">${esc(s.name)}${s.completed?' · Concluída':''}</option>`).join('');
        step.value=selected?String(selected):'';
        if(selected&&step.value!==String(selected))throw new Error('A etapa não está disponível neste projeto.');
      }
    }catch(e){if(run===sequence){failed=true;error.textContent=e.message;}}
    finally{if(run===sequence){loading=false;step.disabled=root.hidden;}}
  }
  project.onchange=()=>steps();
  return {
    async load(selected='',selectedStep=''){
      const run=++catalogSequence;++sequence;
      loading=true;failed=false;project.disabled=true;
      try{
        const rows=await api('/projects'+(archived?'?archived=1':''));
        if(run!==catalogSequence)return;
        project.innerHTML='<option value="">Selecione um projeto</option>'+rows.map(p=>`<option value="${p.id}">${esc(p.name)}${p.archived_at?' · Arquivado':p.status==='completed'?' · Concluído':''}</option>`).join('');
        project.value=selected?String(selected):'';
        if(selected&&project.value!==String(selected))throw new Error('Projeto indisponível. Selecione outro ou restaure o projeto arquivado.');
        await steps(selectedStep);
      }catch(e){if(run===catalogSequence){failed=true;error.textContent=e.message;loading=false;}}
      finally{if(run===catalogSequence)project.disabled=root.hidden;}
    },
    values(){
      if(loading||failed)throw new Error('Aguarde o carregamento ou selecione novamente o projeto.');
      if(!project.value)throw new Error('Selecione um projeto.');
      return {project_id:Number(project.value),step_id:step.value?Number(step.value):null,subject_id:null,topic_id:null,session_kind:'study'};
    }
  };
}
