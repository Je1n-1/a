import {projectPicker} from './project-picker.js';
import {
  topicPicker
} from './topics.js';
import {
  $,
  esc,
  api,
  send,
  dialog,
  toast
} from './api.js';
import {
  localInput
} from './study-format.js';
import {
  clock,
  timestamp,
  date
} from './study-format.js';

export async function editSession(id, subjects, onSaved) {
  const s = await api(`/sessions/${id}`),
    operation_key = crypto.randomUUID();
  const options = subjects.map(x => `<option value="${x.id}" ${x.id===s.subject_id?'selected':''}>${esc(x.name)} · ${esc(x.course_name)}${x.archived_at||x.course_archived_at?' (arquivada)':''}</option>`).join('');
  let picker, workPicker;
  const el = dialog('Corrigir sessão', `
  <p>Você está corrigindo a sessão inteira: <strong>${clock(s.effective_seconds)}</strong> líquidos e ${clock(s.break_seconds)} de pausas curtas e ${clock(s.rest_seconds)} de intervalos. O motivo e os valores anteriores ficarão registrados.</p>
  <div data-project-picker ${s.project_id?'':'hidden'}></div><div ${s.project_id?'hidden':''}><label>Disciplina<select name="subject_id"><option value="">Estudo avulso</option>${options}</select></label>
  <div data-topic-picker hidden></div><label data-free ${s.subject_id?'hidden':''}>Nome do estudo<input name="title" maxlength="200" value="${esc(s.title)}"></label></div>
  <label>Tempo da sessão<select name="mode"><option value="keep">Manter horários, estudo, pausas e intervalos</option><option value="duration">Substituir por duração em uma data</option><option value="times">Substituir por início e fim, sem pausas ou intervalos</option></select></label>
  <p data-warning class="correction-warning" hidden>Esta opção substitui os horários, pausas e intervalos pelo tempo líquido informado. O registro original fica na trilha de alterações.</p>
  <div data-duration hidden><label>Data<input type="date" name="date" value="${s.local_date}" disabled></label><div class="duration-fields"><label>Horas<input type="number" name="hours" min="0" max="24" value="${Math.floor(s.effective_seconds/3600)}" disabled></label><label>Minutos<input type="number" name="minutes" min="0" max="59" value="${Math.floor(s.effective_seconds%3600/60)}" disabled></label><label>Segundos<input type="number" name="seconds" min="0" max="59" value="${s.effective_seconds%60}" disabled></label></div></div>
  <div data-times hidden><label>Início<input name="started_at" type="datetime-local" step="1" value="${s.started_at?localInput(s.started_at):''}" disabled></label><label>Fim<input name="ended_at" type="datetime-local" step="1" value="${s.ended_at?localInput(s.ended_at):''}" disabled></label><p class="field-help">Fuso America/Sao_Paulo. Informe um intervalo contínuo de estudo.</p></div>
  <label>O que fiz?<textarea name="note" maxlength="5000">${esc(s.note)}</textarea></label>
  <label>Motivo da correção<textarea name="reason" required maxlength="1000" placeholder="Ex.: esqueci o relógio ligado por 10 minutos."></textarea></label>`, async values => {
    const duration_seconds = Number(values.hours || 0) * 3600 + Number(values.minutes || 0) * 60 + Number(values.seconds || 0);
    await send(`/sessions/${id}`, {
      ...values,
      ...(s.project_id?workPicker.values():picker.values()),
      subject_id: values.subject_id ? Number(values.subject_id) : null,
      duration_seconds,
      version: s.correction_version,
      operation_key
    }, 'PATCH');
    toast('Correção salva com histórico de alterações.');
    await onSaved();
  }, 'Salvar correção');
  if(s.project_id){workPicker=projectPicker($('[data-project-picker]',el),{archived:true});await workPicker.load(s.project_id,s.step_id);}
  picker = topicPicker($('[data-topic-picker]', el), {
    allowCreate: false,
    legacy: true
  });
  await picker.load(s.subject_id, s.topic_id, s.session_kind);
  $('[name=subject_id]', el).onchange = e => {
    $('[data-free]', el).hidden = !!e.target.value;
    picker.load(e.target.value);
  };
  $('[name=mode]', el).onchange = e => {
    $('[data-warning]', el).hidden = e.target.value === 'keep';
    for (const mode of ['duration', 'times']) {
      const block = $(`[data-${mode}]`, el),
        visible = e.target.value === mode;
      block.hidden = !visible;
      block.querySelectorAll('input').forEach(i => {
        i.disabled = !visible;
        i.required = visible;
      });
    }
  };
}

export async function showCorrections(id) {
  const rows = await api(`/sessions/${id}/corrections`);
  const labels = {
    title: 'Atividade',
    project_name: 'Projeto',
    step_name: 'Etapa',
    subject_label: 'Disciplina / curso',
    note: 'Nota',
    topic_name: 'Tópico',
    session_kind: 'Tipo da sessão',
    local_date: 'Data',
    started_at: 'Início',
    ended_at: 'Fim',
    effective_seconds: 'Tempo líquido',
    break_seconds: 'Pausas curtas',
    rest_seconds: 'Intervalos programados',
    allocation_mode: 'Forma do tempo'
  };
  const value = (key, v) => key.endsWith('seconds') ? clock(v) : key === 'local_date' ? date(v) : ['started_at', 'ended_at'].includes(key) ? timestamp(v) : key === 'allocation_mode' ? ({
    original: 'Registro original',
    duration: 'Duração informada',
    times: 'Horários informados'
  } [v]) : v ?? 'Estudo avulso';
  dialog('Histórico de alterações', rows.length ? rows.map(r => `<article class="audit-entry"><h3>Versão ${r.version} · ${esc(timestamp(r.created_at))}</h3><p><strong>Motivo:</strong> ${esc(r.reason)}</p>${Object.entries(labels).filter(([key])=>r.old_values[key]!==r.new_values[key]).map(([key,label])=>`<p><strong>${label}:</strong><br>${esc(value(key,r.old_values[key]))} → ${esc(value(key,r.new_values[key]))}</p>`).join('')}</article>`).join('') : '<p>Esta sessão ainda não foi corrigida.</p>', null);
}
