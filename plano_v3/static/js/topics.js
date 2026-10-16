import {topicImport} from './topic-import.js';
import {
  $,
  api,
  send,
  esc,
  dialog,
  toast
} from './api.js';
import {
  clock
} from './study-format.js';

export function topicPicker(container, {
  allowCreate = true,
  allowBulk = false,
  legacy = false
} = {}) {
  container.innerHTML = `<label>Tópico <span class="muted">(conteúdo da disciplina)</span><select data-topic aria-label="Tópico"><option value="">Sem tópico informado</option></select></label><label data-new-topic hidden>Novo tópico<input data-topic-name placeholder="Um título de até 200 caracteres"></label>${allowBulk?'<button type="button" class="inline-link" data-bulk-topics>Colar conteúdo para separar em tópicos</button>':''}<label>Tipo da sessão<select data-kind aria-label="Tipo da sessão">${legacy ? '<option value="">Não informado no registro original</option>' : ''}<option value="study">Estudo</option><option value="review">Revisão</option></select></label><p data-topic-error class="form-error" role="alert"></p>`;
  let subject = null,
    sequence = 0,
    loading = false,
    failed = false;
  const select = $('[data-topic]', container),
    name = $('[data-topic-name]', container),
    kind = $('[data-kind]', container);

  function changed() {
    const fresh = select.value === 'new';
    $('[data-new-topic]', container).hidden = !fresh;
    name.required = fresh;
    kind.querySelector('[value=review]').disabled = !select.value;
    if (!select.value && kind.value === 'review') kind.value = 'study';
  }
  select.onchange = changed;
  const picker = {
    async load(subjectId, selected = '', sessionKind = legacy ? '' : 'study') {
      subject = subjectId ? Number(subjectId) : null;
      const request = ++sequence;
      container.hidden = !subject;
      select.innerHTML = '<option value="">Sem tópico informado</option>';
      name.value = '';
      kind.value = sessionKind || '';
      failed = false;
      loading = !!subject;
      select.disabled = loading;
      $('[data-topic-error]', container).textContent = loading ? 'Carregando tópicos…' : '';
      changed();
      if (!subject) return;
      try {
        const rows = await api('/topics?archived=1&subject_id=' + subject);
        if (request !== sequence) return;
        if (!Array.isArray(rows)) throw new Error('Não foi possível ler os tópicos. Selecione a disciplina novamente.');
        select.innerHTML += rows.map(t => `<option value="${t.id}">${esc(t.name)}${t.needs_review ? ' · Revisão necessária' : t.completed ? ' · Concluído' : ''}</option>`).join('') + (allowCreate ? '<option value="new">+ Criar tópico agora</option>' : '');
        select.value = selected ? String(selected) : '';
        kind.value = sessionKind || (legacy ? '' : 'study');
        if (selected && select.value !== String(selected)) throw new Error('O tópico não está disponível nesta disciplina. Selecione outro.');
        changed();
        $('[data-topic-error]', container).textContent = '';
      } catch (error) {
        if (request !== sequence) return;
        failed = true;
        $('[data-topic-error]', container).textContent = error.message;
      } finally {
        if (request === sequence) {
          loading = false;
          select.disabled = false;
        }
      }
    },
    values() {
      if (loading || failed) throw new Error('Aguarde os tópicos ou selecione a disciplina novamente para tentar carregar.');
      if (!subject) return {
        topic_id: null,
        session_kind: kind.value || (legacy ? null : 'study')
      };
      if (select.value === 'new' && !name.value.trim()) throw new Error('Informe o nome do tópico.');
      return {
        topic_id: select.value && select.value !== 'new' ? Number(select.value) : null,
        new_topic_name: select.value === 'new' ? name.value.trim() : undefined,
        session_kind: kind.value || null
      };
    }
  };
  $('[data-bulk-topics]', container)?.addEventListener('click', () => {
    if (!subject) return;
    const subjectId = subject;
    const el = dialog('Separar conteúdo em tópicos', '<div data-topic-import></div>', null);
    topicImport($('[data-topic-import]', el), subjectId, {
      text: name.value,
      onBack: () => el.close(),
      onSaved: async () => {el.close(); if (subject === subjectId) await picker.load(subjectId);}
    });
  });
  return picker;
}

export async function openTopics(subject = null, courseId = null) {
  const query = subject ? 'subject_id=' + subject.id : 'review=1';
  const el = dialog(subject ? 'Tópicos · ' + subject.name : 'Tópicos para revisão', '<div data-topic-list>Carregando…</div>', null);
  const root = $('[data-topic-list]', el);
  async function draw() {
    const rows = (await api('/topics?' + query)).filter(t => !courseId || t.course_id === courseId);
    root.innerHTML = `${subject ? '<div data-add-topic class="topic-create"><label>Novo tópico<input name="name" required placeholder="Conteúdo a estudar"></label><button type="button" class="button secondary" data-create-topic>Adicionar</button></div><button type="button" class="button secondary" data-import-topics>Colar conteúdo para separar</button>' : ''}<p class="field-help">Concluir e precisar de revisão são escolhas independentes. Os tempos abaixo incluem apenas sessões finalizadas.</p><p data-error class="form-error" role="alert"></p>${rows.length ? rows.map(t => `<article class="topic-item"><strong>${esc(t.name)}</strong>${!subject ? `<small>${esc(t.subject_name)} · ${esc(t.course_name)}</small>` : ''}<small>${clock(t.effective_seconds)} registrados · ${t.sessions} sessão(ões)</small><div class="topic-controls"><label class="check-line"><input type="checkbox" data-topic-id="${t.id}" data-field="completed" ${t.completed ? 'checked' : ''}> Concluído</label><label class="check-line"><input type="checkbox" data-topic-id="${t.id}" data-field="needs_review" ${t.needs_review ? 'checked' : ''}> Precisa de revisão</label><a class="button secondary small" href="/?subject=${t.subject_id}&topic=${t.id}&kind=${t.needs_review ? 'review' : 'study'}">${t.needs_review ? 'Revisar' : 'Estudar'}</a>${subject?`<button type="button" class="inline-link" data-split-topic="${t.id}">Separar este texto</button>`: ''}</div></article>`).join('') : '<p>Nenhum tópico nesta lista.</p>'}`;
    function split(text = '') {
      topicImport(root, subject.id, {text, onBack: draw, onSaved: draw});
    }
    $('[data-import-topics]', root)?.addEventListener('click', () => split());
    root.querySelectorAll('[data-split-topic]').forEach(button => {
      button.onclick = () => split(rows.find(t => t.id === Number(button.dataset.splitTopic)).name);
    });
    $('[data-create-topic]', root)?.addEventListener('click', async e => {
      e.preventDefault();
      e.stopPropagation();
      const button = e.currentTarget;
      button.disabled = true;
      try {
        await send('/topics', {
          subject_id: subject.id,
          name: $('[data-add-topic] input', root).value
        });
        await draw();
        toast('Tópico disponível.');
      } catch (error) {
        $('[data-error]', root).textContent = error.message;
        button.disabled = false;
      }
    });
    root.onchange = async e => {
      const input = e.target.closest('[data-topic-id]');
      if (!input) return;
      const topic = rows.find(t => t.id === Number(input.dataset.topicId));
      const field = input.dataset.field,
        desired = input.checked;
      root.querySelectorAll('input,button').forEach(x => x.disabled = true);
      try {
        const saved = await send('/topics/' + topic.id, {
          version: topic.version,
          [field]: desired
        }, 'PATCH');
        if (saved.id !== topic.id || saved[field] !== Number(desired)) throw new Error('Resposta inesperada. Atualize a lista para conferir o tópico.');
        await draw();
        toast('Tópico atualizado.');
      } catch (error) {
        input.checked = !!topic[field];
        $('[data-error]', root).textContent = error.message;
        root.querySelectorAll('input,button').forEach(x => x.disabled = false);
      }
    };
  }
  try {
    await draw();
  } catch (error) {
    root.textContent = error.message;
  }
}
