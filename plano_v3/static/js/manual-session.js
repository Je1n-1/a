import {projectPicker} from './project-picker.js';
import {
  topicPicker
} from './topics.js';
import {
  $,
  esc,
  send,
  dialog,
  toast
} from './api.js';

import {
  localInput
} from './study-format.js';

export function openManual(subjects, onSaved, {projectId=null}={}) {
  const operationKey = crypto.randomUUID();
  const options = subjects.map(s => `<option value="${s.id}">${esc(s.name)} · ${esc(s.course_name)}</option>`).join('');
  let picker, workPicker;
  const el = dialog(projectId?'Registrar trabalho':'Registrar estudo', `
  <p class="field-help">Horários no fuso America/Sao_Paulo. Informe somente o tempo de atividade, sem pausas ou intervalos.</p>
  <div data-project-picker ${projectId?'':'hidden'}></div><div ${projectId?'hidden':''}><label>Disciplina<select name="subject_id"><option value="">Estudo avulso</option>${options}</select></label>
  <div data-topic-picker hidden></div><label data-free>Nome do estudo<input name="title" maxlength="200" placeholder="Estudo avulso"></label></div>
  <label>Como deseja informar?<select name="mode"><option value="duration">Duração, sem horários</option><option value="times">Horário de início e fim</option></select></label>
  <div data-duration class="dialog-grid"><label>Data<input name="date" type="date" value="${localInput(Date.now()).slice(0,10)}" required></label><label>Duração em minutos<input name="minutes" type="number" min="1" max="1440" step="1" required></label></div>
  <div data-times hidden><label>Início<input name="started_at" type="datetime-local" step="1" disabled></label><label>Fim<input name="ended_at" type="datetime-local" step="1" disabled></label></div>
  <label>O que fiz? <span class="muted">(opcional)</span><textarea name="note" maxlength="5000"></textarea></label>`, async values => {
    await send('/sessions/manual', {
      ...values,
      ...(projectId?workPicker.values():picker.values()),
      subject_id: projectId?null:values.subject_id ? Number(values.subject_id) : null,
      duration_seconds: values.mode === 'duration' ? Number(values.minutes) * 60 : undefined,
      operation_key: operationKey
    });
    toast(projectId?'Trabalho registrado.':'Estudo manual registrado.');
    await onSaved();
  }, 'Salvar estudo');
  if(projectId){workPicker=projectPicker($('[data-project-picker]',el));workPicker.load(projectId);}
  picker = topicPicker($('[data-topic-picker]', el));
  $('[name=subject_id]', el).onchange = e => {
    $('[data-free]', el).hidden = !!e.target.value;
    picker.load(e.target.value);
  };
  $('[name=mode]', el).onchange = e => {
    const times = e.target.value === 'times';
    $('[data-duration]', el).hidden = times;
    $('[data-times]', el).hidden = !times;
    el.querySelectorAll('[data-duration] input').forEach(i => {
      i.disabled = times;
      i.required = !times;
    });
    el.querySelectorAll('[data-times] input').forEach(i => {
      i.disabled = !times;
      i.required = times;
    });
  };
}
