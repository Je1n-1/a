import {
  $,
  esc,
  api,
  send,
  labels
} from './api.js';
export function openImport(course, onComplete) {
  const el = $('#import-dialog');
  let busy = false,
    rows = [],
    source = 'file',
    sheets = [];
  const close = () => {
    if (!busy) el.close();
  };
  el.oncancel = e => {
    if (busy) e.preventDefault();
  };

  function head(subtitle) {
    return `<header class="dialog-heading"><div><p class="eyebrow">${esc(course.name)}</p><h2>Importar grade curricular</h2></div><button type="button" class="icon-button" data-close aria-label="Fechar importação">×</button></header><p class="muted">${subtitle}</p>`;
  }

  function wireClose() {
    el.querySelector('[data-close]').onclick = close;
    el.querySelector('[data-cancel]').onclick = close;
  }

  function setBusy(value) {
    busy = value;
    el.querySelectorAll('button,input,select,textarea').forEach(x => x.disabled = value);
    const progress = $('.form-progress', el);
    if (progress) progress.textContent = value ? 'Lendo grade… PDFs em imagem usam OCR local e podem levar alguns segundos.' : '';
  }

  function sourceForm() {
    el.innerHTML = `<form>${head('Primeiro, vamos ler o arquivo. Nada será salvo antes da sua confirmação.')}<div class="tabs" role="group" aria-label="Origem da grade"><button type="button" data-tab="file" aria-pressed="true">Arquivo</button><button type="button" data-tab="text" aria-pressed="false">Colar texto</button></div><div id="file-source"><label>Arquivo da grade<input type="file" name="file" accept=".xlsx,.csv,.tsv,.txt,.docx,.pdf"></label><p class="field-help">XLSX, CSV, TSV, TXT, DOCX ou PDF · até 5 MB.<br>PDFs em imagem: OCR local no Windows, até 12 páginas. Confira nomes e cargas antes de salvar.</p><label id="sheet-label" hidden>Escolha a planilha<select name="sheet"></select></label><a class="inline-link" href="/static/downloads/modelo_grade_curricular.xlsx" download>Baixar modelo de planilha ↗</a></div><div id="text-source" hidden><label>Texto da grade<textarea name="text" rows="8" placeholder="Disciplina&#9;Código&#9;Período&#9;Carga (h)&#10;Circuitos&#9;001&#9;1º período&#9;60"></textarea></label><p class="field-help">Cole as células da planilha, texto com nomes ou conteúdo separado por vírgula, ponto e vírgula ou tabulação.</p></div><p class="form-error" role="alert"></p><div class="dialog-actions"><button type="button" class="button secondary" data-cancel>Cancelar</button><button class="button primary" type="submit">Ler grade →</button></div></form>`;
    source = 'file';
    const progress = document.createElement('p');
    progress.className = 'form-progress field-help';
    progress.setAttribute('role', 'status');
    $('.form-error', el).before(progress);
    sheets = [];
    wireClose();
    $('[name=file]', el).onchange = () => {
      $('#sheet-label', el).hidden = true;
      sheets = [];
    };
    el.querySelectorAll('[data-tab]').forEach(b => b.onclick = () => {
      source = b.dataset.tab;
      el.querySelectorAll('[data-tab]').forEach(x => x.setAttribute('aria-pressed', x === b));
      $('#file-source', el).hidden = source !== 'file';
      $('#text-source', el).hidden = source !== 'text';
      $('.form-error', el).textContent = '';
    });
    $('form', el).onsubmit = async e => {
      e.preventDefault();
      if (busy) return;
      $('.form-error', el).textContent = '';
      let options;
      try {
        if (source === 'file') {
          const file = $('[name=file]', el).files[0];
          if (!file) throw new Error('Escolha um arquivo.');
          const form = new FormData();
          form.append('file', file);
          if (sheets.length) form.append('sheet', $('[name=sheet]', el).value);
          options = {
            method: 'POST',
            body: form
          };
        } else options = {
          method: 'POST',
          body: JSON.stringify({
            text: $('[name=text]', el).value
          })
        };
        setBusy(true);
        const data = await api(`/courses/${course.id}/import/preview`, options);
        setBusy(false);
        if (data.requires_sheet_selection) {
          sheets = data.sheets.filter(s => s.compatible && !s.ignored);
          $('#sheet-label', el).hidden = false;
          $('[name=sheet]', el).innerHTML = sheets.map(s => `<option>${esc(s.name)}</option>`).join('');
          $('.form-error', el).textContent = 'Há mais de uma planilha. Escolha uma e clique em Ler grade.';
          return;
        }
        rows = data.items.map(r => ({
          ...r,
          notes: [r.notes, r.start_date || r.end_date ? `Datas da grade original: ${r.start_date||'—'} a ${r.end_date||'—'}` : ''].filter(Boolean).join('\n')
        }));
        reviewForm(data);
      } catch (error) {
        setBusy(false);
        $('.form-error', el).textContent = error.message;
      }
    };
  }

  function reviewForm(data) {
    el.innerHTML = `<form>${head('Revise as linhas, marque o que entra e confirme. Você pode editar antes de salvar.')}<div class="import-summary"><div><strong id="selection-count"></strong><p>${esc(data.selected_sheet||data.format.toUpperCase())} · nenhuma disciplina salva nesta prévia</p></div><label class="check-line"><input type="checkbox" id="select-all"> Selecionar todas</label></div>${data.warnings?.length?`<p class="field-help">${data.warnings.map(esc).join(' · ')}</p>`:''}<div class="import-rows">${rows.map((r,i)=>`<section class="import-row" data-row="${i}"><label class="check-line"><input type="checkbox" data-field="include" data-index="${i}" ${r.include?'checked':''}> Incluir linha ${i+1}</label><div class="import-fields"><label>Disciplina<input data-field="name" data-index="${i}" maxlength="200" value="${esc(r.name)}"></label><label>Código<input data-field="code" data-index="${i}" maxlength="80" value="${esc(r.code)}"></label><label>Período<input data-field="period" data-index="${i}" maxlength="100" value="${esc(r.period)}"></label><label>Carga (h)<input data-field="hours" data-index="${i}" type="number" step="any" min="0.016666" max="10000" value="${r.workload_minutes?r.workload_minutes/60:''}"></label><label>Situação<select data-field="academic_status" data-index="${i}">${!r.academic_status?'<option value="">Escolha…</option>':''}${Object.entries(labels).map(([k,label])=>`<option value="${k}" ${r.academic_status===k?'selected':''}>${label}</option>`).join('')}</select></label></div>${r.duplicate?`<div class="import-duplicate"><span>Nome já identificado neste curso${r.duplicate.kind==='preview'?' ou nesta prévia':''}.</span><select data-field="duplicate_action" data-index="${i}" aria-label="Ação para duplicada da linha ${i+1}"><option value="skip">Ignorar duplicada</option>${r.duplicate.kind==='existing'?'<option value="update">Atualizar existente</option>':''}</select></div>`:''}${r.warnings?.length?`<p class="row-warnings">${r.warnings.map(esc).join(' · ')}</p>`:''}<details><summary>Observações da linha</summary><textarea aria-label="Observações da linha ${i+1}" data-field="notes" data-index="${i}" maxlength="5000">${esc(r.notes)}</textarea></details></section>`).join('')}</div><p class="form-error" role="alert"></p><div class="dialog-actions"><button type="button" class="button ghost" id="back-source">Outra origem</button><button type="button" class="button secondary" data-cancel>Cancelar</button><button class="button primary" type="submit" id="confirm-import">Confirmar importação</button></div></form>`;
    wireClose();
    $('#back-source', el).onclick = sourceForm;

    function update() {
      const count = rows.filter(r => r.include).length;
      $('#selection-count', el).textContent = `${rows.length} identificada(s) / ${count} selecionada(s)`;
      $('#confirm-import', el).textContent = `Importar ${count} disciplina(s)`;
      $('#confirm-import', el).disabled = count === 0;
      $('#select-all', el).checked = count === rows.length;
      $('#select-all', el).indeterminate = count > 0 && count < rows.length;
      rows.forEach((r, i) => {
        const section = $(`[data-row="${i}"]`, el);
        section.classList.toggle('unselected', !r.include);
        section.querySelectorAll('input:not([type=checkbox]),select,textarea').forEach(input => {
          input.disabled = !r.include;
          input.required = r.include && ['name', 'academic_status'].includes(input.dataset.field);
        });
      });
    }
    $('#select-all', el).onchange = e => {
      rows.forEach((r, i) => {
        r.include = e.target.checked;
        $(`[data-field=include][data-index="${i}"]`, el).checked = r.include;
      });
      update();
    };
    el.querySelectorAll('[data-field]').forEach(input => input.addEventListener('input', () => {
      const r = rows[Number(input.dataset.index)];
      const field = input.dataset.field;
      if (field === 'include') {
        r.include = input.checked;
        update();
      } else if (field === 'hours') r.workload_minutes = input.value === '' ? null : Math.round(Number(input.value) * 60);
      else r[field] = input.value;
    }));
    $('form', el).onsubmit = async e => {
      e.preventDefault();
      if (busy) return;
      $('.form-error', el).textContent = '';
      try {
        if (!rows.some(r => r.include)) throw new Error('Selecione pelo menos uma linha.');
        const payload = rows.map(r => ({
          include: !!r.include,
          name: r.name,
          code: r.code || '',
          period: r.period || '',
          workload_minutes: r.workload_minutes,
          academic_status: r.academic_status,
          notes: r.notes || '',
          duplicate_action: r.duplicate_action || 'skip'
        }));
        setBusy(true);
        const result = await send(`/courses/${course.id}/import/confirm`, {
          confirmed: true,
          items: payload
        });
        el.close();
        await onComplete(result);
      } catch (error) {
        $('.form-error', el).textContent = error.message;
      } finally {
        setBusy(false);
        update();
      }
    };
    update();
  }
  sourceForm();
  el.showModal();
}
