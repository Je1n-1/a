import {moduleGroups} from './module-groups.js';
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
    el.innerHTML = `<form>${head('Revise as linhas, marque o que entra e confirme. Você pode editar antes de salvar.')}<div class="import-summary"><div><strong id="selection-count"></strong><p>${esc(data.selected_sheet||data.format.toUpperCase())} · nenhuma disciplina salva nesta prévia</p></div><label class="check-line"><input type="checkbox" id="select-all"> Selecionar todas</label></div>${data.warnings?.length?`<p class="field-help">${data.warnings.map(esc).join(' · ')}</p>`:''}<div class="import-rows">${rows.map((r,i)=>`<section class="import-row" data-row="${i}"><label class="check-line"><input type="checkbox" data-field="include" data-index="${i}" ${r.include?'checked':''}> Incluir linha ${i+1}</label><details class="import-detail" ${r.errors?.length?'open':''}><summary><strong data-row-name>${esc(r.name||'Nome não informado')}</strong><span>${r.workload_minutes?new Intl.NumberFormat('pt-BR').format(r.workload_minutes/60)+' h':'Carga não informada'} · ${r.errors?.length?'Corrigir dados':r.duplicate?'Duplicada':'Nova disciplina'}</span><span>Conferir / editar</span></summary>${r.errors?.length?`<p class="form-error">${r.errors.map(esc).join(' · ')}</p>`:''}<div class="import-fields"><label>Disciplina<input data-field="name" data-index="${i}" maxlength="200" value="${esc(r.name)}"></label><label>Código<input data-field="code" data-index="${i}" maxlength="80" value="${esc(r.code)}"></label><label>Período<input data-field="period" data-index="${i}" maxlength="100" value="${esc(r.period)}"></label><label>Carga (h)<input data-field="hours" data-index="${i}" type="number" step="any" min="0.016666" max="10000" value="${r.workload_minutes?r.workload_minutes/60:''}"></label><label>Situação<select data-field="academic_status" data-index="${i}">${!r.academic_status?'<option value="">Escolha…</option>':''}${Object.entries(labels).map(([k,label])=>`<option value="${k}" ${r.academic_status===k?'selected':''}>${label}</option>`).join('')}</select></label></div>${r.duplicate?`<div class="import-duplicate"><span>Nome já identificado neste curso${r.duplicate.kind==='preview'?' ou nesta prévia':''}.</span><select data-field="duplicate_action" data-index="${i}" aria-label="Ação para duplicada da linha ${i+1}"><option value="skip">Ignorar duplicada</option>${r.duplicate.kind==='existing'?'<option value="update">Atualizar existente</option>':''}</select></div>`:''}${r.warnings?.length?`<p class="row-warnings">${r.warnings.map(esc).join(' · ')}</p>`:''}<details><summary>Observações da linha</summary><textarea aria-label="Observações da linha ${i+1}" data-field="notes" data-index="${i}" maxlength="5000">${esc(r.notes)}</textarea></details></details></section>`).join('')}</div><p class="form-error" role="alert"></p><div class="dialog-actions"><button type="button" class="button ghost" id="back-source">Outra origem</button><button type="button" class="button secondary" data-cancel>Cancelar</button><button class="button primary" type="submit" id="confirm-import">Confirmar importação</button></div></form>`;
    const container=$('.import-rows',el);
    const blocks=moduleGroups(rows.map((r,index)=>({...r,index})));
    for (const block of blocks) {
      const section=document.createElement('section');
      section.className='import-module';
      section.innerHTML=`<header><h3>${esc(block.name)}</h3><span>${block.rows.length} componente(s) · ${new Intl.NumberFormat('pt-BR').format(block.rows.reduce((sum,r)=>sum+(r.workload_minutes||0),0)/60)} h</span></header>`;
      for (const row of block.rows) section.append(container.querySelector(`[data-row="${row.index}"]`));
      container.append(section);
    }
    if (data.ocr?.repeated_rows) {
      const warning=document.createElement('div');warning.className='recovery-notice';warning.setAttribute('role','alert');
      warning.innerHTML=`<strong>Possível grade incompleta no PDF</strong><p>Foram lidas ${data.ocr.pages} páginas, com ${data.ocr.repeated_rows} linhas repetidas. Restaram ${rows.length} componentes únicos. Confira se o arquivo repete uma janela da grade antes de importar.</p><label class="check-line"><input type="checkbox" id="ack-partial">Conferi o conteúdo e quero importar estas linhas.</label>`;
      container.before(warning);
    }
    el.addEventListener('invalid', e => {
      e.target.closest('.import-detail')?.setAttribute('open', '');
    }, true);
    wireClose();
    $('#back-source', el).onclick = sourceForm;

    function update() {
      const count = rows.filter(r => r.include).length;
      $('#selection-count', el).textContent = `${rows.length} identificada(s) / ${count} selecionada(s)`;
      $('#confirm-import', el).textContent = `Importar ${count} disciplina(s)`;
      $('#confirm-import', el).disabled = count === 0 || ($('#ack-partial',el) && !$('#ack-partial',el).checked);
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
    if ($('#ack-partial',el)) $('#ack-partial',el).onchange=update;
    el.querySelectorAll('[data-field]').forEach(input => input.addEventListener('input', () => {
      const r = rows[Number(input.dataset.index)];
      const field = input.dataset.field;
      if (field === 'include') {
        r.include = input.checked;
        update();
      } else if (field === 'hours') r.workload_minutes = input.value === '' ? null : Math.round(Number(input.value) * 60);
      else {
        r[field] = input.value;
        if (field === 'name') $('[data-row-name]', input.closest('.import-row')).textContent = input.value || 'Nome não informado';
      }
    }));
    $('form', el).onsubmit = async e => {
      e.preventDefault();
      if (busy) return;
      $('.form-error', el).textContent = '';
      try {
        if (!rows.some(r => r.include)) throw new Error('Selecione pelo menos uma linha.');
        if ($('#ack-partial',el) && !$('#ack-partial',el).checked) throw new Error('Confira o aviso de possível grade incompleta.');
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
