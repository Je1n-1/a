import {$, api, esc, send, toast} from './api.js';

const externalPrompt = `Leia o PDF da disciplina que anexei e extraia os tópicos/conteúdos programáticos que devo cadastrar como tópicos de estudo.

Regras:
- Priorize a seção chamada "Cronograma de atividades", "Conteúdos", "Conteúdo programático" ou equivalente.
- Extraia somente os conteúdos de aprendizagem e preserve a ordem e os nomes usados no documento.
- Se o cronograma separar o conteúdo em módulos, aulas ou unidades, mantenha essa identificação junto ao título (ex.: "Unidade 1 — ...").
- Não inclua ementa repetida, objetivos, competências, metodologia, bibliografia, carga horária nem datas.
- Itens que sejam apenas prova, avaliação ou entrega de atividade devem ficar fora da lista de conteúdos.
- Não invente, complete nem reescreva conteúdos que não estejam legíveis no PDF. Se algo estiver ilegível ou ambíguo, avise depois da lista.
- Remova numeração de página e marcadores de lista, mas preserve números que façam parte do título.

Responda somente com um tópico por linha, sem introdução, sem numeração e sem cercas de código. Vou revisar e importar essas linhas no meu controle de estudos.`;

function copyText(text) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  const field = document.createElement('textarea');
  field.value = text;
  field.setAttribute('readonly', '');
  field.style.position = 'fixed';
  field.style.opacity = '0';
  document.body.append(field);
  field.select();
  const copied = document.execCommand('copy');
  field.remove();
  if (!copied) throw new Error('Não consegui copiar automaticamente. Selecione e copie o roteiro exibido abaixo.');
  return Promise.resolve();
}

export function topicImport(root, subjectId, {text = '', onBack, onSaved}) {
  root.onchange = null;
  root.innerHTML = `<p>Importe um PDF pesquisável ou cole uma lista preparada manualmente/por uma IA externa. Nada é salvo até você confirmar os tópicos selecionados.</p>
    <section class="topic-import-source" aria-labelledby="topic-pdf-heading">
      <div><h3 id="topic-pdf-heading">Ler PDF nesta máquina</h3><p class="field-help">O arquivo é processado localmente pelo site e não é armazenado. Funciona melhor quando o texto pode ser selecionado no PDF.</p></div>
      <label>Arquivo PDF<input data-pdf type="file" accept="application/pdf,.pdf"></label>
      <div class="actions"><button type="button" class="button primary" data-pdf-preview>Ler PDF e gerar prévia</button><button type="button" class="button secondary" data-copy-prompt>Copiar roteiro para IA externa</button></div>
      <details data-prompt-details><summary>Ver roteiro para copiar manualmente</summary><pre data-prompt-text></pre></details>
    </section>
    <label>Ou cole os tópicos / conteúdo<textarea data-source rows="6" placeholder="Cole aqui um tópico por linha, o conteúdo da disciplina ou a resposta da IA externa">${esc(text)}</textarea></label>
    <label>Como separar<select data-split-mode><option value="lines">Um tópico por linha ou marcador</option><option value="pages">Sumário com números de página</option><option value="semicolon">Por ponto e vírgula</option></select></label>
    <p class="field-help">Para texto corrido com páginas (ex.: Instalações 6 Projetos 15), use o modo de sumário. Números que fazem parte do título precisam ser conferidos. Em PDFs escaneados, use o roteiro para IA externa ou cole o texto reconhecido pelo computador.</p>
    <div class="actions"><button type="button" class="button secondary" data-preview>Gerar prévia do texto</button><button type="button" class="button ghost" data-back>Voltar aos tópicos</button></div>
    <p data-import-error class="form-error" role="alert"></p><div data-preview-list></div>`;
  const source = $('[data-source]', root), mode = $('[data-split-mode]', root), file = $('[data-pdf]', root), list = $('[data-preview-list]', root);
  const error = $('[data-import-error]', root);
  const promptText = $('[data-prompt-text]', root);
  promptText.textContent = externalPrompt;
  let busy = false;
  const invalidate = () => {list.innerHTML = ''; error.textContent = '';};
  source.oninput = invalidate;
  mode.onchange = invalidate;
  file.onchange = invalidate;
  $('[data-back]', root).onclick = onBack;
  async function perform(fn) {
    if (busy) return;
    busy = true; error.textContent = '';
    const controls = [...root.querySelectorAll('button,input,textarea,select')];
    controls.forEach(x => x.disabled = true);
    try {await fn();} catch (e) {error.textContent = e.message;}
    finally {busy = false; controls.forEach(x => x.disabled = false);}
  }
  const row = item => {
    const name = typeof item === 'string' ? item : item.name;
    const duplicate = typeof item === 'object' && item.duplicate;
    const assessment = typeof item === 'object' && item.kind === 'assessment';
    const checked = !duplicate && !assessment;
    const meta = [assessment ? 'Item avaliativo — desmarcado inicialmente' : '', item?.page ? `Página ${item.page}` : ''].filter(Boolean).join(' · ');
    return `<div class="topic-import-row"><label class="check-line"><input type="checkbox" data-include ${checked?'checked':''}> Adicionar</label><label>Título do tópico<textarea data-name rows="3" aria-label="Título do tópico">${esc(name)}</textarea><small data-length></small></label>${meta?`<small class="field-help">${esc(meta)}</small>`:''}${duplicate?'<small>Já existe ou está repetido nesta prévia. Será ignorado se continuar igual.</small>':''}<button type="button" class="button ghost small" data-remove>Remover da prévia</button></div>`;
  };
  function lengths() {
    list.querySelectorAll('[data-name]').forEach(input => {
      const count = input.value.trim().length;
      const label = input.parentElement.querySelector('[data-length]');
      label.textContent = `${count}/200 caracteres${count > 200 ? ' — divida ou encurte este título' : ''}`;
      label.className = count > 200 ? 'form-error' : 'field-help';
    });
  }
  function showPreview(result, sourceLabel) {
    const contentCount = result.rows.filter(r => r.kind !== 'assessment').length;
    const assessmentCount = result.rows.length - contentCount;
    const countLabel = sourceLabel === 'PDF'
      ? `${contentCount} conteúdo(s)${assessmentCount ? ` · ${assessmentCount} item(ns) avaliativo(s)` : ''}`
      : `${result.rows.length} tópicos`;
    list.innerHTML = `<h3>Prévia do ${sourceLabel}: ${countLabel}</h3><p class="field-help">${esc(result.warning)}</p><div data-rows>${result.rows.map(row).join('')}</div><div class="actions"><button type="button" class="button secondary" data-add-row>Adicionar linha</button><button type="button" class="button primary" data-confirm>Adicionar tópicos selecionados</button></div>`;
    lengths();
    list.scrollIntoView({block: 'start'});
    list.oninput = lengths;
    list.onclick = e => {
      if (e.target.closest('[data-remove]')) e.target.closest('.topic-import-row').remove();
      if (e.target.closest('[data-add-row]')) {
        $('[data-rows]', list).insertAdjacentHTML('beforeend', row(''));
        lengths();
        [...list.querySelectorAll('[data-name]')].at(-1).focus();
      }
      if (e.target.closest('[data-confirm]')) {
        const names = [...list.querySelectorAll('.topic-import-row')].filter(r => $('[data-include]', r).checked).map(r => $('[data-name]', r).value.trim());
        perform(async () => {
          if (!names.length || names.some(n => !n || n.length > 200)) throw new Error('Selecione tópicos com títulos de 1 a 200 caracteres. Nenhum texto será cortado automaticamente.');
          const saved = await send(`/subjects/${subjectId}/topics/confirm`, {names});
          toast(`${saved.created} tópico(s) adicionado(s). ${saved.skipped} repetido(s) ignorado(s).`);
          await onSaved();
        });
      }
    };
  }
  $('[data-copy-prompt]', root).onclick = () => perform(async () => {
    await copyText(externalPrompt);
    toast('Roteiro copiado. Anexe o PDF à IA externa, cole o roteiro e depois cole as linhas geradas aqui.');
    $('[data-prompt-details]', root).open = true;
  });
  $('[data-preview]', root).onclick = () => perform(async () => {
    const result = await send(`/subjects/${subjectId}/topics/preview`, {text: source.value, mode: mode.value});
    showPreview(result, 'texto');
  });
  $('[data-pdf-preview]', root).onclick = () => perform(async () => {
    if (!file.files?.[0]) throw new Error('Escolha o PDF da disciplina.');
    const form = new FormData();
    form.append('file', file.files[0]);
    const result = await api(`/subjects/${subjectId}/topics/pdf-preview`, {method: 'POST', body: form});
    showPreview(result, 'PDF');
  });
}
