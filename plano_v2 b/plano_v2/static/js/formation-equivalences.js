// Aproveitamento na formação; usa as mesmas regras do vínculo individual.
import {$,$$,esc,statuses,hours,api,notify,announce,openDialog,bindSubmit,closeSaved,operationKey} from './workspace-ui.js';
import {comparisonSide} from './equivalence-preview.js';

const endpoint = id => `/api/curriculum-workspace/formations/${id}/equivalences`;
const normalize = value => String(value).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
const key = pair => `${pair.left.id}:${pair.right.id}`;
const assessment = value => value == null ? 'Não informado' : value === 0 ? '0 (registro histórico)' : `${value}/5`;
const footer = label => `<p class="form-error" role="alert"></p><div class="form-actions"><button type="button" data-close>Cancelar</button><button type="submit" class="primary">${label}</button></div>`;

export async function openFormationEquivalences(formationId, onSaved) {
  let overview = await api(endpoint(formationId));
  const selected = new Set();
  let query = '', onlyCompleted = false;

  function showList() {
    openDialog('Aproveitar disciplinas entre formações', `<form>
      <p><strong>${esc(overview.formation.name)}</strong> · Compare matérias de outros cursos para compartilhar conteúdos e, se desejar, aproveitar conclusões.</p>
      <div class="equivalence-filters"><label class="field">Buscar disciplina ou formação<input type="search" id="equivalence-search" value="${esc(query)}"></label>
      <label><input type="checkbox" id="only-completed" ${onlyCompleted?'checked':''}> Mostrar somente possíveis conclusões</label></div>
      <p class="small-note">Correspondência de nome ou carga não confirma equivalência. Nenhum vínculo ou conclusão é selecionado automaticamente.</p>
      <div class="equivalence-selection"><button type="button" id="select-visible">Selecionar correspondências visíveis</button><button type="button" id="clear-selected">Limpar seleção</button><span id="selected-count" aria-live="polite"></span></div>
      <div id="formation-equivalence-list"></div>
      <details class="manual-equivalence"><summary>Não encontrou uma correspondência? Escolher disciplinas manualmente</summary>
        <div class="form-grid"><label class="field">Disciplina desta formação<select id="manual-left"><option value="">Escolha</option>${overview.subjects.map(r=>`<option value="${r.id}">${esc(r.name)}</option>`).join('')}</select></label>
        <label class="field">Disciplina de outro curso<select id="manual-right"><option value="">Escolha</option>${overview.other_subjects.map(r=>`<option value="${r.id}">${esc(r.formation_name)} · ${esc(r.name)}</option>`).join('')}</select></label></div>
        <button type="button" id="manual-compare">Comparar este par</button><p class="small-note">A comparação manual funciona mesmo quando os nomes são diferentes.</p>
      </details>${footer('Comparar selecionadas →')}</form>`, '1 DE 2 · ESCOLHER CORRESPONDÊNCIAS', true);

    function visiblePairs() {
      return overview.pairs.filter(p=>(!onlyCompleted||p.can_complete) && normalize(`${p.left.name} ${p.right.name} ${p.right.formation_name}`).includes(normalize(query)));
    }
    function selectable(p) { return p.kind === 'suggestion' || (p.kind === 'linked' && p.can_complete); }
    function count() { $('#selected-count').textContent=`${selected.size} selecionada(s)`; }
    function render() {
      $('#formation-equivalence-list').innerHTML=visiblePairs().map(p=>`<article class="formation-equivalence-row">
        <label class="equivalence-choice"><input type="checkbox" data-pair="${key(p)}" ${selected.has(key(p))?'checked':''} ${selectable(p)?'':'disabled'} aria-label="Selecionar ${esc(p.left.name)} com ${esc(p.right.formation_name)}">
        <span><strong>${esc(p.left.name)}</strong><small>${hours(p.left.workload_minutes)} · ${statuses[p.left.academic_status]}</small><span>↔ ${esc(p.right.name)}</span><small>${esc(p.right.formation_name)} · ${hours(p.right.workload_minutes)} · ${statuses[p.right.academic_status]}</small></span></label>
        <div class="equivalence-row-actions"><span class="badge">${p.kind==='linked'?'Conteúdos compartilhados':p.kind==='separate'?'Mantidas separadas':p.can_complete?'Conclusão disponível para aproveitar':'Possível correspondência'}</span>
        <a href="/curriculum/${p.left.id}?tab=equivalences&return=${encodeURIComponent(location.pathname+location.search)}">Ver disciplina e vínculos</a>
        ${p.kind!=='linked'?`<button type="button" data-decision="${p.kind==='separate'?'reconsider':'separate'}" data-pair="${key(p)}">${p.kind==='separate'?'Rever decisão':'Manter separado'}</button>`:''}</div></article>`).join('') || '<p class="empty">Nenhuma correspondência neste filtro. Você também pode escolher um par manualmente abaixo.</p>';
      count();
    }
    $('#equivalence-search').oninput=e=>{query=e.target.value;render();};
    $('#only-completed').onchange=e=>{onlyCompleted=e.target.checked;render();};
    $('#select-visible').onclick=()=>{visiblePairs().filter(selectable).forEach(p=>selected.add(key(p)));render();};
    $('#clear-selected').onclick=()=>{selected.clear();render();};
    $('#formation-equivalence-list').onchange=e=>{
      if(!e.target.matches('input[data-pair]'))return;
      if(e.target.checked)selected.add(e.target.dataset.pair);else selected.delete(e.target.dataset.pair);
      count();
    };
    $('#formation-equivalence-list').onclick=async e=>{
      const button=e.target.closest('[data-decision]');if(!button)return;
      const [left,right]=button.dataset.pair.split(':').map(Number);button.disabled=true;
      try {
        const result=await api(`/api/curriculum-workspace/${left}/equivalences/${right}/decision`,{method:'POST',body:JSON.stringify({decision:button.dataset.decision,operation_key:operationKey()})});
        selected.delete(button.dataset.pair);announce(result.affected);
        overview=await api(endpoint(formationId));render();await onSaved();
      } catch(error) { $('#dialog-body .form-error').textContent=error.message; }
      finally {button.disabled=false;}
    };
    $('#manual-compare').onclick=async e=>{
      const button=e.currentTarget;button.disabled=true;
      try {
        const left_id=Number($('#manual-left').value),right_id=Number($('#manual-right').value);
        if(!left_id||!right_id)throw new Error('Escolha uma disciplina de cada formação.');
        await comparePairs([{left_id,right_id}]);
      }catch(error){$('#dialog-body .form-error').textContent=error.message;}
      finally{button.disabled=false;}
    };
    bindSubmit(async()=>{
      if(!selected.size)throw new Error('Selecione pelo menos uma correspondência.');
      await comparePairs([...selected].map(value=>{const [left_id,right_id]=value.split(':').map(Number);return {left_id,right_id};}));
    });
    render();
  }

  async function comparePairs(pairs) {
    const preview=await api(endpoint(formationId)+'/preview',{method:'POST',body:JSON.stringify({pairs})});
    const side=comparisonSide;
    openDialog('Confirmar compartilhamento e aproveitamento',`<form>
      <p class="notice">Conteúdos e autoavaliações serão compartilhados nos pares confirmados. Todos os históricos permanecem na origem. Situação acadêmica, carga, período, datas e observações continuam independentes.</p>
      ${preview.pairs.map((p,i)=>`<section class="equivalence-review" data-review="${i}"><h3>${i+1}. ${p.already_linked?'Vínculo já confirmado':'Confirmar este vínculo'}</h3>
      <div class="compare-grid">${p.sides.map(side).join('')}</div>
      ${p.members.length>2?`<p>Formações deste grupo: ${p.members.map(r=>esc(r.formation_name)).join(', ')}.</p>`:''}
      ${p.conflicts.map(k=>`<label class="field">Escolha ${k==='mastery'?'o domínio':'a dificuldade'} compartilhado<select data-assessment="${k}" required><option value="">Escolha uma avaliação</option>${p.sides.map(s=>`<option value="${s.curriculum.id}">${esc(s.curriculum.formation_name)} · ${assessment(s.personal[k])}</option>`).join('')}</select></label>`).join('')}
      ${p.completed_sources.length?`<fieldset class="completion-options"><legend>Aproveitar conclusão (opcional)</legend><p>Já concluída em ${esc(p.completed_sources[0].formation_name)}. Marque somente os destinos que deseja concluir:</p>${p.members.filter(r=>r.academic_status!=='completed').map(r=>`<label class="destination"><input type="checkbox" data-completion="${r.id}"><span><strong>Concluir ${esc(r.name)} em ${esc(r.formation_name)}</strong><small>Situação atual: ${statuses[r.academic_status]}</small></span></label>`).join('')||'<p>Todas as ocorrências já estão concluídas.</p>'}</fieldset>`:'<p class="small-note">Nenhuma conclusão será registrada: não há disciplina concluída neste grupo.</p>'}</section>`).join('')}
      <p class="small-note">Sem marcar destinos, as situações acadêmicas não mudam. O aproveitamento é sua decisão de acompanhamento, não um reconhecimento oficial da instituição. Notas e datas não serão copiadas.</p>
      <button type="button" id="back-to-equivalences">← Voltar à seleção</button>${footer('Confirmar escolhas')}</form>`,'2 DE 2 · REVISAR ANTES DE SALVAR',true);
    $('#back-to-equivalences').onclick=showList;
    bindSubmit(async form=>{
      const payload=preview.pairs.map((p,i)=>{
        const section=$(`[data-review="${i}"]`,form);
        return {left_id:p.left_id,right_id:p.right_id,version:p.version,
          assessment_choices:Object.fromEntries($$('[data-assessment]',section).map(n=>[n.dataset.assessment,Number(n.value)])),
          completion_targets:$$('[data-completion]:checked',section).map(n=>Number(n.dataset.completion))};
      });
      const result=await api(endpoint(formationId)+'/confirm',{method:'POST',body:JSON.stringify({confirmed:true,pairs:payload,operation_key:form.dataset.operationKey})});
      closeSaved();announce(result.affected);
      notify(`${result.linked_pairs} vínculo(s) confirmado(s); ${result.completed_subjects} conclusão(ões) aproveitada(s).`);
      await onSaved();
    });
  }
  showList();
}
