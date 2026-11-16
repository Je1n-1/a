import { $, api, send, esc, toast } from './api.js';
import { clock } from './study-format.js';

const state = { subjectId: null, context: null, prompt: '', document: null, decisions: {}, preview: null, expectedVersion: 0 };

export async function loadStudyRoute(subjectId) {
  return api(`/subjects/${Number(subjectId)}/study-route`);
}

function promptFor(context) {
  const {subject:s, route, topics} = context;
  const topicContext = topics.map(t => ({id:t.id,title:t.name,completed:!!t.completed,needs_review:!!t.needs_review,minutes_recorded:Math.floor(t.effective_seconds/60),sessions:t.sessions}));
  const routeContext = route ? {title:route.title,description:route.description,modules:route.modules.map(m=>({key:m.module_key,title:m.title,description:m.description,topics:m.topics.map(t=>({key:t.item_key,existing_topic_id:t.id,title:t.name,description:t.route_description,estimated_minutes:t.estimated_minutes,source_reference:t.source_reference}))}))} : null;
  const schema = {schema_version:1,kind:'subject_study_route',route:{title:'Roteiro principal',description:'Organização dos conteúdos da disciplina.',modules:[{key:'fundamentos',title:'Fundamentos',description:'',topics:[{key:'grandezas_e_unidades',title:'Grandezas e unidades',description:'',estimated_minutes:60,source_reference:'Plano de ensino, unidade 1',existing_topic_id:null}]}]}};
  return `Analise o PDF do plano de ensino/ementa que anexarei a esta conversa e proponha um roteiro de estudo para a disciplina abaixo. O PDF será enviado por mim diretamente a você; o Plano não recebe nem armazena o arquivo.

CONTEXTO DA DISCIPLINA
Curso: ${s.course_name}
Instituição: ${s.institution || 'não informada'}
Disciplina: ${s.name}
Código: ${s.code || 'não informado'}
Período: ${s.period || 'não informado'}
Carga horária cadastrada: ${s.workload_minutes ? `${Math.round(s.workload_minutes/60*100)/100} horas` : 'não informada'}

TÓPICOS JÁ CADASTRADOS (IDs são canônicos; preserve estado e histórico)
${JSON.stringify(topicContext, null, 2)}

ROTEIRO ATUAL PARA ATUALIZAÇÃO (null quando ainda não existe)
${JSON.stringify(routeContext, null, 2)}

INSTRUÇÕES
1. Organize fielmente os conteúdos em módulos e tópicos, respeitando terminologia e ordem do documento quando existir.
2. Não invente conteúdos, pré-requisitos, páginas, avaliações ou cargas horárias que o documento não sustente.
3. Divida tópicos extensos em unidades claras, sem fragmentar excessivamente.
4. Preserve os tópicos cadastrados. Reutilize existing_topic_id somente quando houver correspondência real; em caso de dúvida, use null.
5. Não atribua status, conclusão, revisão, horas realizadas ou sessões.
6. Não imponha calendário, datas ou rotina obrigatória.
7. Use keys curtas, únicas no roteiro, em snake_case ASCII. Não use key como identidade permanente.
8. Responda somente com JSON válido, sem Markdown, comentários ou cercas de código. O Plano valida e importa o JSON; não aceite alterar a disciplina de destino.

CONTRATO JSON
${JSON.stringify(schema, null, 2)}

Limites: até 30 módulos e 300 tópicos no total; títulos até 200 caracteres; descrições até 2.000; referência até 500. estimated_minutes é opcional, inteiro positivo até 600.000. Use existing_topic_id null ou um ID da lista acima.`;
}

function topicState(t) {
  if (t.needs_review) return 'Revisão pendente';
  if (t.completed) return 'Concluído';
  if (t.effective_seconds > 0) return 'Em andamento';
  return 'Não iniciado';
}

function routeSummary(context) {
  const r = context.route;
  if (!r) return '<p class="muted">Ainda não há roteiro para esta disciplina.</p>';
  return `<div class="study-route-summary"><div><strong>${esc(r.title)}</strong><p>${esc(r.description || '')}</p><small>${r.module_count} módulo(s) · ${r.topic_count} tópico(s) · versão ${r.version}</small></div></div><div class="study-route-modules">${r.modules.map(m=>`<details><summary>${esc(m.title)} <span>${m.topics.length} tópico(s)</span></summary><ul>${m.topics.map(t=>`<li><span>${esc(t.name)}</span><small>${esc(topicState(t))}${t.estimated_minutes?` · ${t.estimated_minutes} min previstos`:''}${t.source_reference?` · ${esc(t.source_reference)}`:''}</small></li>`).join('')}</ul></details>`).join('')}</div>${context.outside_topics.length?`<details class="route-outside"><summary>${context.outside_topics.length} tópico(s) fora do roteiro</summary><ul>${context.outside_topics.map(t=>`<li>${esc(t.name)} · ${esc(topicState(t))}</li>`).join('')}</ul></details>`:''}`;
}

function cleanDocument(doc) {
  return {schema_version:1,kind:'subject_study_route',route:{title:doc.route.title,description:doc.route.description||'',modules:doc.route.modules.map(m=>({key:m.key,title:m.title,description:m.description||'',topics:m.topics.map(t=>({key:t.key,title:t.title,description:t.description||'',estimated_minutes:t.estimated_minutes??null,source_reference:t.source_reference||'',existing_topic_id:t.existing_topic_id??null}))}))}};
}

function previewMarkup() {
  if (!state.preview) return '';
  const p = state.preview;
  const warningText = p.warnings.map(w => {
    if (w.type === 'duplicate_in_json') return `Título repetido no JSON: ${esc(w.title)}.`;
    if (w.type === 'same_topic_twice') return `O mesmo tópico canônico aparece mais de uma vez (ID ${w.topic_id}).`;
    if (w.type === 'ambiguous_match') return `Correspondência aproximada para “${esc(p.document.route.modules.flatMap(m=>m.topics).find(t=>t.key===w.key)?.title || '')}”: escolha o vínculo ou marque como novo.`;
    return '';
  }).filter(Boolean);
  const modules = p.document.route.modules.map(m=>`<section class="route-preview-module"><h4>${esc(m.title)}</h4>${m.description?`<p>${esc(m.description)}</p>`:''}<ul>${m.topics.map(t=>{
    const matched = t.existing_topic;
    const candidates = p.warnings.find(w=>w.type==='ambiguous_match'&&w.key===t.key)?.candidates || [];
    const decision = state.decisions[t.key];
    const select = candidates.length ? `<label class="route-match">Vínculo<select data-route-decision="${esc(t.key)}"><option value="">Escolha…</option><option value="new" ${decision?.action==='new'?'selected':''}>Criar tópico novo</option>${candidates.map(c=>`<option value="${c.id}" ${decision?.topic_id===c.id?'selected':''}>Usar “${esc(c.name)}” · ${c.completed?'Concluído':c.needs_review?'Revisão pendente':clock(c.effective_seconds)+' registrados'}</option>`).join('')}</select></label>` : '';
    return `<li class="route-preview-item"><div><strong>${esc(t.title)}</strong><small>${matched?`Vinculado a tópico existente · ${esc(topicState(matched))}`:t.match==='choice_required'?'Correspondência precisa de decisão':t.match==='exact'?'Correspondência exata':'Tópico novo'}${t.estimated_minutes?` · ${t.estimated_minutes} min`:''}${t.source_reference?` · ${esc(t.source_reference)}`:''}</small>${t.description?`<p>${esc(t.description)}</p>`:''}${select}</div><button type="button" class="button ghost small" data-remove-route-topic="${esc(t.key)}" aria-label="Remover ${esc(t.title)}">Remover</button></li>`;
  }).join('')}</ul></section>`).join('');
  const blockers = warningText.length ? `<div class="route-warnings" role="alert"><strong>Revise antes de confirmar</strong><ul>${warningText.map(w=>`<li>${w}</li>`).join('')}</ul><p>Você pode editar o JSON, remover tópicos repetidos ou escolher os vínculos aproximados.</p></div>` : '';
  return `<div class="route-preview"><p><strong>${esc(p.document.route.title)}</strong> · ${p.document.route.modules.length} módulo(s) · ${p.document.route.modules.reduce((n,m)=>n+m.topics.length,0)} tópico(s)</p>${blockers}${modules}</div>`;
}

function renderDialog(mode='summary', error='') {
  const el = $('#common-dialog');
  const context = state.context;
  const summary = routeSummary(context);
  const promptSection = `<section class="study-route-prompt"><label>Prompt pronto para copiar<textarea readonly rows="7" data-route-prompt>${esc(state.prompt)}</textarea></label><button type="button" class="button secondary" data-copy-route-prompt>Copiar prompt para IA externa</button><p class="field-help">Anexe o PDF diretamente à IA que você usa. Nenhum arquivo ou mensagem é enviado pelo Plano.</p></section>`;
  const importSection = `<section class="study-route-import"><label>Resposta JSON da IA<textarea data-route-json rows="8" placeholder="Cole aqui o JSON completo retornado pela IA">${esc(state.document ? JSON.stringify(cleanDocument(state.document), null, 2) : '')}</textarea></label><div class="actions"><button type="button" class="button secondary" data-route-preview>Gerar prévia</button></div>${previewMarkup()}</section>`;
  const content = `<form method="dialog"><header class="dialog-heading"><div><p class="eyebrow">ROTEIRO DA DISCIPLINA</p><h2>${esc(context.subject.name)}</h2><small>${esc(context.subject.course_name)}${context.subject.institution?` · ${esc(context.subject.institution)}`:''}</small></div><button type="button" class="icon-button" data-route-close aria-label="Fechar">×</button></header><div class="dialog-content"><div class="study-route-existing"><h3>${context.route?'Roteiro principal':'Roteiro de estudo'}</h3>${summary}<div class="actions"><button type="button" class="button secondary" data-route-copy>Copiar prompt</button><button type="button" class="button primary" data-route-import>${context.route?'Atualizar roteiro':'Colar resposta JSON'}</button></div></div>${mode==='import'?importSection:mode==='prompt'?promptSection:''}<p class="form-error" role="alert" data-route-error>${esc(error)}</p><div class="dialog-actions"><button type="button" class="button secondary" data-route-close>Fechar</button>${mode==='import'&&state.preview?`<button type="button" class="button primary" data-route-confirm ${state.preview.warnings.length||state.preview.has_unresolved_choices?'disabled':''}>Confirmar importação</button>`:''}</div></div></form>`;
  el.innerHTML = content;
  if (!el.open) el.showModal();
  el.querySelectorAll('[data-route-close]').forEach(b=>b.onclick=()=>el.close());
  $('[data-route-copy]',el).onclick=()=>{renderDialog('prompt');};
  $('[data-route-import]',el).onclick=()=>{state.preview=null;state.decisions={};renderDialog('import');};
  $('[data-copy-route-prompt]',el)?.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(state.prompt);toast('Prompt copiado. Anexe o PDF diretamente à IA externa.');}catch{ $('[data-route-error]',el).textContent='Não foi possível copiar automaticamente. Selecione e copie o texto do campo.';}});
  $('[data-route-preview]',el)?.addEventListener('click',()=>runPreview(el));
  $('[data-route-json]',el)?.addEventListener('input',()=>{
    if (!state.preview) return;
    state.preview=null;
    $('.route-preview',el)?.remove();
    const confirm=$('[data-route-confirm]',el);
    if (confirm) confirm.disabled=true;
    $('[data-route-error]',el).textContent='O JSON foi alterado. Gere uma nova prévia antes de confirmar.';
  });
  el.querySelectorAll('[data-route-decision]').forEach(select=>select.onchange=()=>{
    const value=select.value;
    if (!value) delete state.decisions[select.dataset.routeDecision];
    else state.decisions[select.dataset.routeDecision]=value==='new'?{action:'new'}:{action:'existing',topic_id:Number(value)};
    runPreview(el);
  });
  el.querySelectorAll('[data-remove-route-topic]').forEach(button=>button.onclick=()=>{
    const itemKey=button.dataset.removeRouteTopic;
    state.document.route.modules=state.document.route.modules.map(m=>({...m,topics:m.topics.filter(t=>t.key!==itemKey)})).filter(m=>m.topics.length);
    delete state.decisions[itemKey];
    if (!state.document.route.modules.length) { state.preview=null; renderDialog('import','O roteiro precisa manter pelo menos um módulo com tópicos.'); return; }
    $('[data-route-json]',el).value=JSON.stringify(cleanDocument(state.document),null,2);
    runPreview(el);
  });
  $('[data-route-confirm]',el)?.addEventListener('click',()=>confirmImport(el));
}

async function runPreview(el) {
  try {
    const text=$('[data-route-json]',el).value;
    const raw=JSON.parse(text);
    state.decisions={...state.decisions};
    state.preview=await send(`/subjects/${state.subjectId}/study-route/preview`,{document:raw,decisions:state.decisions});
    state.document=state.preview.document;
    renderDialog('import');
  } catch(error) {
    $('[data-route-error]',el).textContent=error instanceof SyntaxError?'O texto não é um JSON válido. Corrija-o e tente gerar a prévia novamente.':error.message;
  }
}

async function confirmImport(el) {
  try {
    const current=state.preview.document;
    const document=cleanDocument(current);
    const result=await send(`/subjects/${state.subjectId}/study-route`,{document,decisions:state.decisions,expected_version:state.expectedVersion,operation_key:crypto.randomUUID()});
    state.context=result;
    state.expectedVersion=result.route.version;
    state.prompt=promptFor(result);
    toast(result.idempotent_replay?'Esta importação já havia sido concluída.':result.unchanged?'Este roteiro já estava atualizado; nada foi alterado.':'Roteiro salvo. Os tópicos e históricos existentes foram preservados.');
    renderDialog('summary');
    if (state.onSaved) await state.onSaved();
  } catch(error) {
    $('[data-route-error]',el).textContent=error.message;
  }
}

export async function openStudyRoute(subjectId, onSaved) {
  state.subjectId=Number(subjectId);
  state.onSaved=onSaved;
  try {
    state.context=await loadStudyRoute(state.subjectId);
    state.expectedVersion=state.context.route?.version||0;
    state.prompt=promptFor(state.context);
    state.document=null;state.decisions={};state.preview=null;
    renderDialog('summary');
  } catch(error) { toast(error.message); }
}
