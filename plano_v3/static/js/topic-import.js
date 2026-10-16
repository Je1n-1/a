import {$, esc, send, toast} from './api.js';

export function topicImport(root, subjectId, {text = '', onBack, onSaved}) {
  root.onchange = null;
  root.innerHTML = `<p>Cole o conteúdo da disciplina e confira cada tópico antes de adicionar. O texto original e os estudos já registrados não serão alterados.</p>
    <label>Conteúdo para separar<textarea data-source rows="7" placeholder="Cole aqui a lista de conteúdos ou o sumário do AVA">${esc(text)}</textarea></label>
    <label>Como separar<select data-split-mode><option value="lines">Um tópico por linha ou marcador</option><option value="pages">Sumário com números de página</option><option value="semicolon">Por ponto e vírgula</option></select></label>
    <p class="field-help">Para texto corrido com páginas (ex.: Instalações 6 Projetos 15), use o modo de sumário. Números que fazem parte do título precisam ser conferidos. Para um print, copie o texto com o reconhecimento de texto do seu computador e cole aqui.</p>
    <div class="actions"><button type="button" class="button secondary" data-preview>Gerar prévia</button><button type="button" class="button ghost" data-back>Voltar aos tópicos</button></div>
    <p data-import-error class="form-error" role="alert"></p><div data-preview-list></div>`;
  const source = $('[data-source]', root), mode = $('[data-split-mode]', root), list = $('[data-preview-list]', root);
  const error = $('[data-import-error]', root);
  let busy = false;
  const invalidate = () => {list.innerHTML = ''; error.textContent = '';};
  source.oninput = invalidate;
  mode.onchange = invalidate;
  $('[data-back]', root).onclick = onBack;
  async function perform(fn) {
    if (busy) return;
    busy = true; error.textContent = '';
    const controls = [...root.querySelectorAll('button,input,textarea,select')];
    controls.forEach(x => x.disabled = true);
    try {await fn();} catch (e) {error.textContent = e.message;}
    finally {busy = false; controls.forEach(x => x.disabled = false);}
  }
  const row = (name, duplicate = false) => `<div class="topic-import-row"><label class="check-line"><input type="checkbox" data-include ${duplicate?'':'checked'}> Adicionar</label><label>Título do tópico<textarea data-name rows="3" aria-label="Título do tópico">${esc(name)}</textarea><small data-length></small></label>${duplicate?'<small>Já existe ou está repetido nesta prévia. Será ignorado se continuar igual.</small>':''}<button type="button" class="button ghost small" data-remove>Remover da prévia</button></div>`;
  function lengths() {
    list.querySelectorAll('[data-name]').forEach(input => {
      const count = input.value.trim().length;
      const label = input.parentElement.querySelector('[data-length]');
      label.textContent = `${count}/200 caracteres${count > 200 ? ' — divida ou encurte este título' : ''}`;
      label.className = count > 200 ? 'form-error' : 'field-help';
    });
  }
  $('[data-preview]', root).onclick = () => perform(async () => {
    const result = await send(`/subjects/${subjectId}/topics/preview`, {text: source.value, mode: mode.value});
    list.innerHTML = `<h3>Revise os ${result.rows.length} tópicos encontrados</h3><p class="field-help">${esc(result.warning)}</p><div data-rows>${result.rows.map(r => row(r.name, r.duplicate)).join('')}</div><div class="actions"><button type="button" class="button secondary" data-add-row>Adicionar linha</button><button type="button" class="button primary" data-confirm>Adicionar tópicos selecionados</button></div>`;
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
    };
    $('[data-confirm]', list).onclick = () => {
      const names = [...list.querySelectorAll('.topic-import-row')].filter(r => $('[data-include]', r).checked).map(r => $('[data-name]', r).value.trim());
      perform(async () => {
        if (!names.length || names.some(n => !n || n.length > 200)) throw new Error('Selecione tópicos com títulos de 1 a 200 caracteres. Nenhum texto será cortado automaticamente.');
        const result = await send(`/subjects/${subjectId}/topics/confirm`, {names});
        toast(`${result.created} tópico(s) adicionado(s). ${result.skipped} repetido(s) ignorado(s).`);
        await onSaved();
      });
    };
  });
}
