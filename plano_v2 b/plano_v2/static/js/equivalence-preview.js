// A comparação individual e a comparação na formação exibem os mesmos registros.
import {esc,statuses,hours} from './workspace-ui.js';

const assessment=value=>value==null?'Não informado':value===0?'0 · valor histórico':`${value} / 5`;
const date=value=>value?new Intl.DateTimeFormat('pt-BR',{timeZone:'America/Sao_Paulo'}).format(new Date(value.length===10?value+'T12:00:00-03:00':value)):'Não informada';
const topicStatuses={not_started:'Não iniciado',in_progress:'Em andamento',completed:'Concluído',paused:'Pausado (legado)',for_review:'Para revisar (legado)'};
const section=(label,rows,render)=>`<details><summary>${label} (${rows.length})</summary>${rows.length?rows.map(render).join(''):'<p>Nenhum registro.</p>'}</details>`;

export function comparisonSide(s){
  const c=s.curriculum;
  return `<section class="compare-side"><h3>${esc(c.name)}</h3><p>${esc(c.formation_name)}</p>
    <dl class="facts"><div><dt>Carga / situação</dt><dd>${hours(c.workload_minutes)} · ${statuses[c.academic_status]}</dd></div>
      <div><dt>Período / módulo</dt><dd>${esc(c.period||'Não informado')}</dd></div>
      <div><dt>Início / fim</dt><dd>${date(c.start_date)} / ${date(c.end_date)}</dd></div>
      <div><dt>Dificuldade / domínio</dt><dd>${assessment(s.personal.difficulty)} / ${assessment(s.personal.mastery)}</dd></div></dl>
    <p>${s.topics.length} tópicos · ${s.session_count} sessões · ${s.note_count} notas</p>
    ${section('Conteúdos preservados',s.topics,t=>`<div class="history-row"><strong>${esc(t.name)}</strong><p>${topicStatuses[t.status]||esc(t.status)}${t.archived_at?' · arquivado':''} · ${esc(t.origin_name)}</p>${t.description?`<p class="preserve-lines">${esc(t.description)}</p>`:''}</div>`)}
    ${section('Sessões preservadas',s.sessions||[],r=>`<div class="history-row"><strong>${date(r.date)} · ${hours(r.duration_seconds/60)}</strong><p>Registro #${r.id} · estudo de origem #${r.study_subject_id}</p>${r.notes?`<p class="preserve-lines">${esc(r.notes)}</p>`:''}</div>`)}
    ${section('Anotações preservadas',s.notes||[],r=>`<div class="history-row"><strong>${esc(r.title)}</strong><p>Nota #${r.id} · estudo de origem #${r.study_subject_id}</p><p class="preserve-lines">${esc(r.content_markdown)}</p></div>`)}
    ${section('Autoavaliações preservadas',s.assessments||[],r=>`<div class="history-row"><strong>${r.kind==='mastery'?'Domínio':'Dificuldade'}${r.topic_id?' · tópico #'+r.topic_id:''}: ${assessment(r.value)}</strong><p>${date(r.recorded_at)} · ${esc(r.origin_formation_name)}</p></div>`)}
  </section>`;
}
