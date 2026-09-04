import {api, localDateISO, weekDates} from "./api.js";

const $ = (selector, root = document) => root.querySelector(selector);
const app = $("#app");
const page = document.body.dataset.page;
const weekdays = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"];
const status = {not_available:"Não disponível",available:"Disponível",in_progress:"Em andamento",completed:"Concluída",failed:"Reprovada",locked:"Bloqueada",exempted:"Dispensada",not_started:"Não iniciado",planned:"Planejada",skipped:"Não realizada",rescheduled:"Reagendada",cancelled:"Cancelada",active:"Ativo",paused:"Pausado",archived:"Arquivado",queued:"Na fila de revisão",reviewed:"Revisada",withdrawn:"Retirada"};
const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[char]));
const hours = value => `${(Number(value || 0) / 3600).toFixed(1).replace(".", ",")} h`;
const empty = (title, message, action = "") => `<div class="empty"><strong>${title}</strong><span>${message}</span>${action}</div>`;
const label = value => status[value] || value || "—";
const toast = message => { $("#toast-root").innerHTML = `<div class="toast">${esc(message)}</div>`; window.setTimeout(() => $("#toast-root").replaceChildren(), 3200); };
const fields = form => Object.fromEntries(new FormData(form));
const weekRange = () => { const dates = weekDates(); return {start: dates[0], end: dates[6], dates}; };
let formationRenderRevision = 0;

function saoPauloTodayISO() {
  const parts = new Intl.DateTimeFormat("en-US", {timeZone:"America/Sao_Paulo", year:"numeric", month:"2-digit", day:"2-digit"}).formatToParts(new Date()).reduce((all, part) => ({...all, [part.type]:part.value}), {});
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function calendarDate(year, month, day = 1) { return new Date(Date.UTC(year, month, day, 12)); }
function calendarDateFromISO(value) { const [year, month, day] = String(value).split("-").map(Number); return calendarDate(year, month - 1, day); }
function calendarISO(value) { return `${value.getUTCFullYear()}-${String(value.getUTCMonth() + 1).padStart(2, "0")}-${String(value.getUTCDate()).padStart(2, "0")}`; }
function calendarAddDays(value, days) { const next = new Date(value); next.setUTCDate(next.getUTCDate() + days); return next; }
function calendarAddMonths(value, months) { return calendarDate(value.getUTCFullYear(), value.getUTCMonth() + months, 1); }
function calendarMonthStart(value) { return calendarDate(value.getUTCFullYear(), value.getUTCMonth(), 1); }
function calendarMonday(value) { return calendarAddDays(value, -((value.getUTCDay() + 6) % 7)); }
function validCalendarDate(value) { if (!/^\d{4}-\d{2}-\d{2}$/.test(value || "")) return null; const parsed = calendarDateFromISO(value); return calendarISO(parsed) === value ? parsed : null; }

const planningView = (() => {
  const params = new URLSearchParams(window.location.search);
  const mode = params.get("view") === "week" ? "week" : "month";
  const initial = validCalendarDate(params.get("date")) || calendarDateFromISO(saoPauloTodayISO());
  return {mode, cursor: mode === "month" ? calendarMonthStart(initial) : initial};
})();

function planningRange() {
  if (planningView.mode === "week") {
    const first = calendarMonday(planningView.cursor);
    const dates = Array.from({length:7}, (_, index) => calendarAddDays(first, index));
    return {first, last:dates.at(-1), dates, start:calendarISO(first), end:calendarISO(dates.at(-1))};
  }
  const monthStart = calendarMonthStart(planningView.cursor);
  const first = calendarMonday(monthStart);
  const nextMonth = calendarAddMonths(monthStart, 1);
  const lastOfMonth = calendarAddDays(nextMonth, -1);
  const last = calendarAddDays(lastOfMonth, 6 - ((lastOfMonth.getUTCDay() + 6) % 7));
  const dates = Array.from({length:Math.round((last - first) / 86400000) + 1}, (_, index) => calendarAddDays(first, index));
  return {first, last, dates, start:calendarISO(first), end:calendarISO(last)};
}

function syncPlanningLocation() {
  if (page !== "planning") return;
  const url = new URL(window.location.href);
  url.searchParams.set("view", planningView.mode);
  url.searchParams.set("date", calendarISO(planningView.cursor));
  window.history.replaceState({}, "", url);
}

function planningToday() { return calendarDateFromISO(saoPauloTodayISO()); }
function planningDefaultDate() {
  const today = saoPauloTodayISO();
  const range = planningRange();
  return today >= range.start && today <= range.end ? today : planningView.mode === "month" ? calendarISO(planningView.cursor) : range.start;
}

const formationView = (() => {
  const params = new URLSearchParams(window.location.search);
  const filter = ["active", "archived", "all"].includes(params.get("filter")) ? params.get("filter") : "active";
  const selectedId = Number(params.get("selected")) || null;
  return {filter, selectedId};
})();

// Estado exclusivamente visual da central de disciplinas. As consultas e as
// alterações continuam sendo confirmadas pelo servidor; esta estrutura não
// representa nem persiste o estado acadêmico.
const curriculumView = {
  formationId: null,
  q: "",
  period: "",
  academicStatus: "",
  reviewStatus: "",
  visibility: "active",
  quick: "all",
  sort: "period",
  selectedIds: new Set(),
};

const studiesView = (() => {
  const params = new URLSearchParams(window.location.search);
  return {
    visibility: ["active", "paused", "review", "completed", "archived", "all"].includes(params.get("study_filter")) ? params.get("study_filter") : "active",
    formationId: params.get("formation_id") || "",
    q: params.get("study_q") || "",
  };
})();

const curriculumAcademicStatuses = ["not_available", "available", "in_progress", "completed", "failed", "locked", "exempted"];
const curriculumReviewStatuses = ["none", "queued", "in_progress", "reviewed"];

function asRows(payload) {
  if (Array.isArray(payload)) return payload;
  return payload?.items || payload?.rows || [];
}

function count(value) { return Number(value && typeof value === "object" ? value.count || 0 : value || 0); }
function plural(value, singular, pluralWord = `${singular}s`) { return `${value} ${value === 1 ? singular : pluralWord}`; }
function curriculumReviewLabel(value) {
  return {none:"Sem revisão", queued:"Para revisar", in_progress:"Revisando", reviewed:"Revisada"}[value || "none"] || "Sem revisão";
}
function curriculumItemTypeLabel(value) { return value === "section" ? "Linha estrutural" : "Disciplina"; }
function isStructuralCurriculum(row) { return row?.item_type === "section"; }
function curriculumIsArchived(row) { return Boolean(row?.archived_at); }
function formatMinutesAsHours(minutes) {
  if (minutes === null || minutes === undefined || minutes === "") return "—";
  const numeric = Number(minutes);
  if (!Number.isFinite(numeric)) return "—";
  const hoursValue = numeric / 60;
  return `${Number.isInteger(hoursValue) ? hoursValue : hoursValue.toFixed(1).replace(".", ",")} h`;
}
function clampPercent(value) { return Math.max(0, Math.min(100, Math.round(Number(value) || 0))); }
function objectCount(object, keys) { return keys.reduce((total, key) => total + count(object?.[key]), 0); }
function studyParentReason(study) {
  const reasons = [];
  if (study?.archived_at) reasons.push("Estudo arquivado");
  if (study?.formation_archived_at || study?.related_formation_archived_at) reasons.push("Formação arquivada");
  if (study?.curriculum_archived_at || study?.discipline_archived_at) reasons.push("Disciplina arquivada");
  return reasons.join(" · ");
}

function syncFormationLocation() {
  if (page !== "formations") return;
  const url = new URL(window.location.href);
  url.searchParams.set("filter", formationView.filter);
  if (formationView.selectedId) url.searchParams.set("selected", String(formationView.selectedId));
  else url.searchParams.delete("selected");
  window.history.replaceState({}, "", url);
}

function syncStudiesLocation() {
  if (page !== "studies") return;
  const url = new URL(window.location.href);
  url.searchParams.set("study_filter", studiesView.visibility);
  if (studiesView.formationId) url.searchParams.set("formation_id", studiesView.formationId); else url.searchParams.delete("formation_id");
  if (studiesView.q) url.searchParams.set("study_q", studiesView.q); else url.searchParams.delete("study_q");
  window.history.replaceState({}, "", url);
}

function modal(title, content, onsubmit) {
  $("#modal-root").innerHTML = `<div class="modal-backdrop"><form class="modal form"><div class="row"><h2>${title}</h2><button class="button ghost" type="button" data-close>×</button></div>${content}<p class="form-error" data-form-error role="alert"></p><div class="form-actions"><button class="button" type="button" data-close>Cancelar</button><button class="button primary">Salvar</button></div></form></div>`;
  const form = $("#modal-root form");
  const save = $(".button.primary", form);
  const closeControls = [...form.querySelectorAll("[data-close]")];
  let busy = false;
  form.onclick = event => { if (!busy && event.target.closest("[data-close]")) $("#modal-root").replaceChildren(); };
  if (onsubmit) form.onsubmit = async event => {
    event.preventDefault();
    if (busy) return;
    const errorMessage = $("[data-form-error]", form);
    busy = true; save.disabled = true; closeControls.forEach(button => { button.disabled = true; }); errorMessage.textContent = "";
    try { await onsubmit(fields(form), form, event); $("#modal-root").replaceChildren(); toast(form.dataset.successMessage || "Alteração salva."); render(); }
    catch (error) { busy = false; save.disabled = false; closeControls.forEach(button => { button.disabled = false; }); errorMessage.textContent = error.message || "Não foi possível salvar."; }
  };
  return form;
}

function confirmAction({title, message, confirmLabel, opener, onConfirm, fallbackLabel, onFallback, onClose, formatError}) {
  const root = $("#modal-root");
  const returnFocus = opener instanceof HTMLElement ? opener : document.activeElement;
  root.innerHTML = `<div class="modal-backdrop" data-confirm-backdrop><section class="modal form" role="dialog" aria-modal="true" aria-labelledby="confirm-title"><h2 id="confirm-title">${esc(title)}</h2><p class="muted">${esc(message)}</p><p class="form-error" id="confirm-error" role="alert"></p><div class="form-actions"><button class="button" type="button" data-confirm-cancel>Cancelar</button>${fallbackLabel ? `<button class="button" type="button" data-confirm-fallback>${esc(fallbackLabel)}</button>` : ""}<button class="button ${confirmLabel.includes("Excluir") ? "danger" : "primary"}" type="button" data-confirm-accept>${esc(confirmLabel)}</button></div></section></div>`;
  const backdrop = $("[data-confirm-backdrop]", root);
  const accept = $("[data-confirm-accept]", root);
  const error = $("#confirm-error", root);
  const controls = [...root.querySelectorAll("button")];
  let busy = false;
  const focusable = () => [...backdrop.querySelectorAll("button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled])")].filter(element => element.offsetParent !== null);
  const onKey = event => {
    if (event.key === "Escape" && !busy) return close();
    if (event.key !== "Tab") return;
    const items = focusable();
    if (!items.length) return event.preventDefault();
    const first = items[0], last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };
  const onBackdrop = event => { if (event.target === backdrop && !busy) close(); };
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    backdrop.removeEventListener("click", onBackdrop);
    document.removeEventListener("keydown", onKey);
    root.replaceChildren();
    onClose?.();
    returnFocus?.focus?.();
  };
  const setBusy = value => { busy = value; controls.forEach(button => { button.disabled = value; }); };
  const fail = exception => { error.textContent = formatError?.(exception) || exception.message || "Não foi possível concluir a ação."; setBusy(false); };
  const run = async operation => {
    if (busy) return;
    setBusy(true); error.textContent = "";
    try { await operation(); close(); await render(); }
    catch (exception) { fail(exception); }
  };
  document.addEventListener("keydown", onKey);
  backdrop.addEventListener("click", onBackdrop);
  $("[data-confirm-cancel]", root).onclick = close;
  accept.onclick = () => run(onConfirm);
  $("[data-confirm-fallback]", root)?.addEventListener("click", () => run(onFallback));
  window.setTimeout(() => accept.focus(), 0);
}

const dependencyLabels = {
  curriculum_subjects:"disciplinas da grade", disciplines:"disciplinas da grade", subjects:"disciplinas", studies:"estudos atuais", study_subjects:"estudos", attempts:"tentativas anteriores", groups:"grupos", topics:"tópicos", planned_sessions:"blocos planejados", planned:"blocos planejados", planned_future:"blocos futuros planejados", planned_cancelled:"blocos cancelados", planned_completed:"blocos concluídos", sessions:"sessões reais", study_sessions:"sessões reais", notes:"anotações", reviews:"revisões", evaluations:"avaliações", formations:"formações", structural_candidates:"linhas estruturais"
};

function dependencyEntries(dependencies = {}) {
  const source = dependencies.dependencies || dependencies.counts || dependencies.summary || dependencies.blockers || dependencies;
  return Object.entries(source || {}).flatMap(([key, value]) => {
    if (typeof value === "number" || typeof value === "string") {
      const numeric = Number(value);
      return Number.isFinite(numeric) && numeric ? [[key, numeric]] : [];
    }
    if (Array.isArray(value)) return value.length ? [[key, value.length]] : [];
    if (value && typeof value === "object" && Number(value.count)) return [[key, Number(value.count)]];
    return [];
  });
}

function dependencySummaryMarkup(dependencies, emptyMessage = "Não há vínculos dependentes.") {
  const entries = dependencyEntries(dependencies);
  if (!entries.length) return `<p class="muted">${esc(emptyMessage)}</p>`;
  const planned = (dependencies.dependencies || dependencies).planned_sessions;
  const byStatus = planned?.by_status || {};
  const statusBreakdown = Object.entries(byStatus).filter(([, value]) => count(value)).map(([key, value]) => `${count(value)} ${label(key).toLocaleLowerCase("pt-BR")}`).join(" · ");
  return `<ul class="dependency-list">${entries.map(([key, value]) => `<li><strong>${value}</strong> ${esc(dependencyLabels[key] || key.replaceAll("_", " "))}${key === "planned_sessions" && statusBreakdown ? `<span>${esc(statusBreakdown)}</span>` : ""}</li>`).join("")}</ul>`;
}

async function openDependencies(kind, ident, name, opener = null) {
  const dependencies = await api(`/${kind}/${ident}/dependencies`);
  const form = modal(`Dependências de ${esc(name)}`, `<p class="muted">Esta prévia mostra o que permanece como histórico ao arquivar e o que exigirá confirmação forte antes de uma exclusão definitiva.</p>${dependencySummaryMarkup(dependencies)}<details class="dependency-raw"><summary>Ver informações detalhadas</summary><pre>${esc(JSON.stringify(dependencies, null, 2))}</pre></details>`, null);
  const save = $(".button.primary", form);
  save?.remove();
  $(".form-actions", form)?.insertAdjacentHTML("beforeend", '<button class="button primary" type="button" data-close>Entendi</button>');
  $("[data-close]", form)?.focus?.();
  if (opener instanceof HTMLElement) form.dataset.returnFocus = "true";
}

async function openTypedDestroy({kind, ident, name, endpoint, opener = null, description = ""}) {
  const dependencies = await api(`/${kind}/${ident}/dependencies`);
  const form = modal(`Excluir ${esc(name)} definitivamente`, `<div class="danger-zone"><p><strong>Esta ação pode apagar dados vinculados e não pode ser desfeita.</strong> Arquivar é a opção segura quando você quer apenas tirar o item da lista atual.</p>${description ? `<p>${esc(description)}</p>` : ""}${dependencySummaryMarkup(dependencies, "Não há dependências. A exclusão removerá somente este registro.")}<label>Para confirmar, digite exatamente <strong>${esc(name)}</strong><input name="confirmation" autocomplete="off" required aria-describedby="typed-confirm-help"></label><p class="field-help" id="typed-confirm-help">A confirmação protege contra exclusão acidental. O servidor também valida o texto e executa a operação em transação.</p></div>`, async values => {
    if (values.confirmation !== name) throw new Error("Digite o nome exatamente como mostrado para confirmar a exclusão.");
    await api(endpoint, {method:"POST", body:JSON.stringify({confirmation:values.confirmation, include_dependencies:true})});
  });
  const save = $(".button.primary", form);
  save.textContent = "Excluir definitivamente";
  save.classList.remove("primary");
  save.classList.add("danger");
  window.setTimeout(() => $("[name=confirmation]", form)?.focus(), 0);
  return form;
}

async function openFormationArchive(current, opener) {
  const dependencies = await api(`/formations/${current.id}/dependencies`);
  const linkedStudies = objectCount(dependencies.dependencies || dependencies, ["studies", "study_subjects", "active_studies"]);
  const form = modal(`Arquivar ${esc(current.name)}`, `<p class="muted">Arquivar preserva disciplinas, sessões, anotações e revisões. Escolha como tratar estudos atuais ligados a esta formação.</p>${dependencySummaryMarkup(dependencies)}<fieldset class="choice-list"><legend>Destino dos estudos vinculados</legend><label><input type="radio" name="study_policy" value="archive_studies" checked> <strong>Arquivar formação e estudos vinculados</strong><span>Recomendado. Estudos ativos ou pausados serão arquivados e somente blocos futuros ainda planejados serão cancelados.</span></label><label><input type="radio" name="study_policy" value="hide_studies"> <strong>Arquivar somente a formação</strong><span>Os estudos permanecem no histórico, mas deixam de aparecer em Estudos atuais porque a formação está arquivada.</span></label></fieldset>${linkedStudies ? "" : '<p class="muted">Não há estudos vinculados ativos para tratar.</p>'}`, async (values, formElement) => {
    const result = await api(`/formations/${current.id}/archive`, {method:"POST", body:JSON.stringify({study_policy:values.study_policy})});
    const archived = count(result?.archived_studies);
    const cancelled = count(result?.cancelled_future_blocks);
    formElement.dataset.successMessage = archived || cancelled ? `${archived ? plural(archived, "estudo") : "Nenhum estudo"} arquivado(s); ${cancelled ? plural(cancelled, "bloco futuro", "blocos futuros") : "nenhum bloco futuro"} cancelado(s).` : "Formação arquivada; nenhum estudo ou bloco futuro precisou ser alterado.";
    formationView.filter = "archived";
    formationView.selectedId = current.id;
    syncFormationLocation();
  });
  $(".button.primary", form).textContent = "Arquivar formação";
  return form;
}

async function openFormationRestore(current, opener) {
  const dependencies = await api(`/formations/${current.id}/dependencies`);
  const form = modal(`Restaurar ${esc(current.name)}`, `<p class="muted">Restaurar a formação não reabre automaticamente estudos encerrados por outro motivo.</p>${dependencySummaryMarkup(dependencies)}<label class="toggle-row"><input type="checkbox" name="restore_studies" value="true"> Restaurar também os estudos que foram arquivados junto com esta formação</label>`, async values => {
    await api(`/formations/${current.id}/restore`, {method:"POST", body:JSON.stringify({restore_studies:values.restore_studies === "true"})});
    formationView.filter = "active";
    formationView.selectedId = current.id;
    syncFormationLocation();
  });
  $(".button.primary", form).textContent = "Restaurar formação";
  return form;
}

function openCurriculumStatus(row) {
  const form = modal(`Estado acadêmico: ${esc(row.name)}`, `<p class="muted">O estado acadêmico e a intenção de revisão são conceitos separados. Concluir a disciplina não elimina uma revisão marcada.</p><label>Estado acadêmico<select name="academic_status">${curriculumAcademicStatuses.map(value => `<option value="${value}" ${value === row.academic_status ? "selected" : ""}>${label(value)}</option>`).join("")}</select></label>`, values => api(`/curriculum/${row.id}/status`, {method:"POST", body:JSON.stringify({academic_status:values.academic_status})}));
  $(".button.primary", form).textContent = "Atualizar estado";
}

function openCurriculumReview(row, desiredStatus = null) {
  const current = row.review_status || "none";
  const form = modal(`Revisão: ${esc(row.name)}`, `<p class="muted">Revisar não muda o estado acadêmico da disciplina.</p><label>Situação da revisão<select name="status">${curriculumReviewStatuses.map(value => `<option value="${value}" ${(desiredStatus || current) === value ? "selected" : ""}>${curriculumReviewLabel(value)}</option>`).join("")}</select></label><label>Prioridade (1 a 5, opcional)<input name="priority" type="number" min="1" max="5" value="${esc(row.review_priority || "")}"></label><label>Observação da revisão<textarea name="notes" placeholder="Ex.: revisar antes da prova.">${esc(row.review_notes || "")}</textarea></label>${row.active_study_id ? "" : '<label class="toggle-row"><input type="checkbox" name="start_study" value="true"> Criar ou restaurar estudo atual para esta revisão</label>'}`, values => api(`/curriculum/${row.id}/review`, {method:"POST", body:JSON.stringify({status:values.status, priority:values.priority ? Number(values.priority) : null, notes:values.notes || null, start_study:values.start_study === "true"})}));
  $(".button.primary", form).textContent = "Salvar revisão";
}

function openStudyFinish(study) {
  const form = modal(`Finalizar ${esc(study.name)}`, `<p class="muted">O resultado atualiza o estado acadêmico da disciplina ligada e registra o encerramento. O histórico de tópicos, sessões e revisões permanece preservado.</p><label>Resultado<select name="result"><option value="approved">Aprovada</option><option value="failed">Reprovada</option><option value="withdrawn">Encerrar sem resultado</option><option value="exempted">Dispensada</option></select></label><label>Nota final (opcional)<input name="final_score" type="number" min="0" step="0.01"></label>`, values => api(`/studies/${study.id}/finish`, {method:"POST", body:JSON.stringify({result:values.result, final_score:values.final_score === "" ? null : Number(values.final_score)})}));
  $(".button.primary", form).textContent = "Finalizar estudo";
}

function openStudyRemoveCurrent(study) {
  const form = modal(`Remover ${esc(study.name)} dos estudos atuais`, `<p class="muted">Isso não apaga histórico. O padrão recomendado arquiva este estudo, devolve a disciplina para disponível e pode cancelar apenas blocos futuros ainda planejados.</p><label>Estado acadêmico após encerrar<select name="resolution"><option value="available">Disponível — recomendado para encerrar sem resultado</option><option value="in_progress">Permanecer em andamento</option><option value="approved">Concluída</option><option value="failed">Reprovada</option><option value="exempted">Dispensada</option></select></label><label class="toggle-row"><input type="checkbox" name="cancel_future_blocks" value="true" checked> Cancelar blocos futuros ainda planejados</label>`, values => api(`/studies/${study.id}/remove-current`, {method:"POST", body:JSON.stringify({resolution:values.resolution, cancel_future_blocks:values.cancel_future_blocks === "true"})}));
  $(".button.primary", form).textContent = "Remover dos atuais";
}

async function topicsFor(studyId) {
  const detail = await api(`/studies/${studyId}`);
  return [...detail.groups.flatMap(group => group.topics), ...detail.ungrouped_topics];
}
function topicOptions(topics, selected) { return `<option value="">Sem tópico</option>${topics.map(topic => `<option value="${topic.id}" ${String(topic.id) === String(selected || "") ? "selected" : ""}>${esc(topic.name)} · ${topic.mastery}/5</option>`).join("")}`; }
function studyOptions(studies, selected) { return studies.map(study => `<option value="${study.id}" ${String(study.id) === String(selected || "") ? "selected" : ""}>${esc(study.name)}</option>`).join(""); }
function card(title, value, note = "") { return `<div class="card"><span class="muted">${title}</span><div class="metric">${value}</div><div class="muted">${note}</div></div>`; }

async function openSession({planned = null, review = null} = {}) {
  const studies = await api("/studies");
  if (!studies.length) return toast("Crie ou adicione um estudo antes de registrar uma sessão.");
  const preferred = planned?.study_subject_id || review?.study_subject_id || studies[0].id;
  const form = modal(planned ? "Começar sessão planejada" : review ? "Registrar revisão" : "Registrar sessão", `<label>Matéria<select name="study_subject_id" id="session-study">${studyOptions(studies, preferred)}</select></label><label>Tópico<select name="topic_id" id="session-topic"></select></label><label>Data<input name="date" type="date" value="${localDateISO()}" required></label><label>Horário inicial (opcional)<input name="started_at" type="datetime-local"></label><label>Duração (minutos)<input name="minutes" type="number" min="1" value="${planned?.planned_duration_minutes || 25}" required></label><label>Domínio depois<select name="mastery_after"><option value="">Não informar</option>${[0,1,2,3,4,5].map(value => `<option value="${value}">${value}/5</option>`).join("")}</select></label><label><input name="topic_completed" type="checkbox" value="true"> Concluí este tópico</label><label>O que foi estudado?<textarea name="notes" placeholder="Dificuldades, exercícios e próximos passos."></textarea></label>`, async values => {
    const seconds = Number(values.minutes) * 60;
    const started = values.started_at ? new Date(values.started_at) : null;
    const ended = started ? new Date(started.getTime() + seconds * 1000) : null;
    const payload = {study_subject_id:Number(values.study_subject_id), topic_id:values.topic_id ? Number(values.topic_id) : null, date:values.date, duration_seconds:seconds, started_at:started?.toISOString(), ended_at:ended?.toISOString(), mastery_after:values.mastery_after === "" ? null : Number(values.mastery_after), topic_completed:values.topic_completed === "true", entry_method:review ? "review" : "manual", notes:values.notes};
    if (planned) payload.planned_session_id = planned.id;
    if (review) {
      await api(`/reviews/${review.id}/complete`, {method:"POST", body:JSON.stringify({rating: review.rating, duration_seconds: seconds, notes: values.notes})});
    } else await api("/sessions", {method:"POST", body:JSON.stringify(payload)});
  });
  const study = $("#session-study", form), topic = $("#session-topic", form);
  const load = async () => { topic.innerHTML = topicOptions(await topicsFor(study.value), planned?.topic_id || review?.topic_id); };
  study.onchange = load; await load();
}

async function startTimer(planned = null, preferredStudyId = null) {
  const studies = await api("/studies");
  if (!studies.length) return toast("Crie um estudo antes de iniciar o foco.");
  const started = new Date();
  const preferred = preferredStudyId || planned?.study_subject_id || studies[0].id;
  const form = modal("Foco em andamento", `<label>Matéria<select name="study_subject_id" id="timer-study">${studyOptions(studies, preferred)}</select></label><label>Tópico<select name="topic_id" id="timer-topic"></select></label><div class="card"><div class="muted">TEMPO DECORRIDO</div><div class="metric" id="timer-clock">00:00:00</div></div><label>Observação<textarea name="notes" placeholder="O que você estudou?"></textarea></label>`, async values => {
    const ended = new Date();
    await api("/sessions", {method:"POST", body:JSON.stringify({study_subject_id:Number(values.study_subject_id), topic_id:values.topic_id ? Number(values.topic_id) : null, planned_session_id:planned?.id || null, date:localDateISO(started), started_at:started.toISOString(), ended_at:ended.toISOString(), duration_seconds:Math.max(1, Math.round((ended - started) / 1000)), entry_method:"timer", notes:values.notes})});
  });
  const study = $("#timer-study", form), topic = $("#timer-topic", form);
  const load = async () => { topic.innerHTML = topicOptions(await topicsFor(study.value), planned?.topic_id); };
  study.onchange = load; await load();
  const interval = window.setInterval(() => { const seconds = Math.floor((Date.now() - started.getTime()) / 1000); $("#timer-clock", form).textContent = new Date(seconds * 1000).toISOString().slice(11, 19); }, 500);
  form.addEventListener("submit", () => window.clearInterval(interval), {once:true});
  form.addEventListener("click", event => { if (event.target.closest("[data-close]")) window.clearInterval(interval); });
}

async function renderToday() {
  const data = await api("/bootstrap"); const today = localDateISO();
  const todayPlan = data.planned.filter(item => item.scheduled_date === today);
  const studiedToday = (await api(`/sessions?start=${today}&end=${today}`)).reduce((sum, item) => sum + item.duration_seconds, 0);
  const rec = data.recommendation;
  app.innerHTML = `<div class="grid kpis">${card("Disponível hoje", `${todayPlan.length} bloco(s)`, "na agenda")}${card("Planejado", hours(todayPlan.reduce((sum, item) => sum + item.planned_duration_minutes * 60, 0)), "sessões ativas")}${card("Estudado hoje", hours(studiedToday), "sessões reais")}${card("Meta diária", "—", "defina metas por matéria")}</div><div class="grid split"><section class="stack"><section class="card">${rec ? `<div class="bar"><div><span class="tag">ESTUDAR AGORA</span><h2>${esc(rec.study_subject.name)}</h2><p class="muted">${esc(rec.topic?.name || "Escolha um tópico")}</p></div><button class="button primary" data-focus>Começar agora · ${rec.recommended_duration} min</button></div><p class="muted">${rec.reasons.map(esc).join(" · ")}</p>` : empty("Nenhuma recomendação", "Crie um estudo com tópico e meta semanal.", `<a class="button" href="/studies">Abrir estudos</a>`)}</section><section class="card"><div class="bar"><h2>Agenda de hoje</h2><a href="/planning" class="button ghost">Planejamento</a></div>${todayPlan.length ? todayPlan.map(item => `<div class="list-item row"><div><strong>${esc(item.subject_name)}</strong><div class="muted">${esc(item.topic_name || "Sessão")} · ${item.start_time || "sem horário"}</div></div><button class="button" data-start-plan="${item.id}">Começar</button></div>`).join("") : empty("Dia livre", "Você pode gerar uma proposta ou adicionar um bloco manual.")}</section></section><aside class="stack"><section class="card"><h2>Revisões pendentes</h2>${data.reviews.length ? data.reviews.slice(0,4).map(item => `<div class="list-item"><strong>${esc(item.topic_name)}</strong><div class="muted">${esc(item.subject_name)} · ${item.due_date}</div></div>`).join("") : empty("Sem revisões pendentes", "Revisões surgem a partir de uma sessão com tópico.")}</section><section class="card"><h2>Progresso por matéria</h2>${data.studies.map(study => `<div class="list-item"><div class="row"><strong>${esc(study.name)}</strong><span>${study.completed_topics}/${study.topic_count} tópicos</span></div><div class="progress"><i style="width:${study.progress_percent}%"></i></div><div class="muted">Progresso ${study.progress_percent}% · domínio ${study.mastery_average}/5</div></div>`).join("") || empty("Sem estudos", "")}</section></aside></div>`;
}

async function openAvailability() {
  const checked = weekdays.map((day, index) => `<label><input type="checkbox" name="weekdays" value="${index}" ${index < 5 ? "checked" : ""}> ${day}</label>`).join("");
  modal("Disponibilidade semanal", `<p class="muted">Escolha dias e uma faixa. Por exemplo: segunda a sexta, 06:00–11:45.</p><div class="check-grid">${checked}</div><label>Início<input name="start_time" type="time" value="06:00" required></label><label>Fim<input name="end_time" type="time" value="11:45" required></label><label>Aplicação<select name="mode"><option value="replace">Substituir as faixas desses dias</option><option value="append">Adicionar faixa</option></select></label>`, async (_, form) => {
    const values = new FormData(form); const days = values.getAll("weekdays").map(Number);
    await api("/availability/batch", {method:"POST", body:JSON.stringify({weekdays:days,start_time:values.get("start_time"),end_time:values.get("end_time"),mode:values.get("mode")})});
  });
}

async function openPlanEditor(id) {
  const [studies, current] = await Promise.all([api("/studies"), id ? api(`/planned/${id}`) : Promise.resolve(null)]);
  if (!studies.length) return toast("Crie um estudo antes de planejar.");
  const form = modal(current ? "Editar bloco planejado" : "Nova sessão planejada", `<label>Matéria<select name="study_subject_id" id="plan-study">${studyOptions(studies, current?.study_subject_id || studies[0].id)}</select></label><label>Tópico<select name="topic_id" id="plan-topic"></select></label><label>Data<input name="scheduled_date" type="date" value="${current?.scheduled_date || planningDefaultDate()}" required></label><label>Horário<input name="start_time" type="time" value="${current?.start_time || ""}"></label><label>Duração (minutos)<input name="planned_duration_minutes" type="number" min="1" value="${current?.planned_duration_minutes || 50}" required></label>`, async values => {
    const payload = {...values,study_subject_id:Number(values.study_subject_id),topic_id:values.topic_id ? Number(values.topic_id) : null,planned_duration_minutes:Number(values.planned_duration_minutes)};
    if (current) await api(`/planned/${id}`, {method:"PATCH",body:JSON.stringify(payload)}); else await api("/planned", {method:"POST",body:JSON.stringify(payload)});
  });
  const study = $("#plan-study", form), topic = $("#plan-topic", form);
  const load = async () => { topic.innerHTML = topicOptions(await topicsFor(study.value), current?.topic_id); }; study.onchange = load; await load();
}

let focusOpening = false;

function openPlanningFocus(plannedId, opener = null) {
  if (focusOpening) return;
  focusOpening = true;
  if (opener instanceof HTMLButtonElement) opener.disabled = true;
  const url = new URL("/focus", window.location.origin);
  if (plannedId) url.searchParams.set("planned_id", String(plannedId));
  window.open(url.href, "_blank", "noopener");
  window.setTimeout(() => {
    focusOpening = false;
    if (opener instanceof HTMLButtonElement && opener.isConnected) opener.disabled = false;
  }, 550);
}

async function openPlanRescheduleEditor(current) {
  const studies = await api("/studies");
  if (!studies.length) return toast("Crie um estudo antes de reagendar.");
  const form = modal("Reagendar bloco", `<p class="muted">O bloco atual ficará marcado como reagendado e uma nova sessão será criada no horário abaixo.</p><label>Matéria<select name="study_subject_id" id="reschedule-study">${studyOptions(studies, current.study_subject_id)}</select></label><label>Tópico<select name="topic_id" id="reschedule-topic"></select></label><label>Nova data<input name="scheduled_date" type="date" value="${current.scheduled_date}" required></label><label>Novo horário<input name="start_time" type="time" value="${current.start_time || ""}"></label><label>Duração (minutos)<input name="planned_duration_minutes" type="number" min="1" value="${current.planned_duration_minutes}" required></label>`, async values => {
    await api(`/planned/${current.id}/reschedule`, {method:"POST", body:JSON.stringify({...values, study_subject_id:Number(values.study_subject_id), topic_id:values.topic_id ? Number(values.topic_id) : null, planned_duration_minutes:Number(values.planned_duration_minutes)})});
  });
  const study = $("#reschedule-study", form), topic = $("#reschedule-topic", form);
  const load = async () => { topic.innerHTML = topicOptions(await topicsFor(study.value), current.topic_id); };
  study.onchange = load;
  await load();
}

async function openPlanActions(id, opener) {
  const current = await api(`/planned/${id}`);
  const form = modal("Bloco planejado", `<div class="planning-block-summary"><strong>${esc(current.subject_name)}</strong><span>${esc(current.topic_name || "Sessão sem tópico")}</span><span>${esc(current.scheduled_date)} · ${esc(current.start_time || "Horário livre")} · ${current.planned_duration_minutes} min</span></div><p class="muted">Cancelar mantém o bloco no histórico como cancelado. Excluir remove o bloco definitivamente.</p>`, null);
  $(".form-actions", form).innerHTML = `<button class="button" type="button" data-close>Fechar</button><button class="button" type="button" data-plan-edit>Editar</button><button class="button primary" type="button" data-plan-start>Começar</button><button class="button" type="button" data-plan-reschedule>Reagendar</button><button class="button" type="button" data-plan-cancel>Cancelar</button><button class="button danger" type="button" data-plan-delete>Excluir</button>`;
  const close = () => $("#modal-root").replaceChildren();
  $("[data-plan-edit]", form).onclick = () => { close(); openPlanEditor(current.id).catch(error => toast(error.message)); };
  $("[data-plan-start]", form).onclick = event => { openPlanningFocus(current.id, event.currentTarget); close(); };
  $("[data-plan-reschedule]", form).onclick = () => { close(); openPlanRescheduleEditor(current).catch(error => toast(error.message)); };
  $("[data-plan-cancel]", form).onclick = () => {
    close();
    confirmAction({title:"Cancelar bloco planejado", message:`Cancelar ${planningBlockSummary(current)}? O bloco ficará registrado como cancelado; para removê-lo de vez, use Excluir.`, confirmLabel:"Cancelar bloco", opener, onConfirm:async () => { await api(`/planned/${current.id}`, {method:"PATCH", body:JSON.stringify({status:"cancelled"})}); toast("Bloco cancelado."); }});
  };
  $("[data-plan-delete]", form).onclick = () => {
    close();
    confirmAction({title:"Excluir bloco definitivamente", message:`Excluir ${planningBlockSummary(current)}? Cancelar preserva o histórico; excluir remove este bloco de forma definitiva.`, confirmLabel:"Excluir definitivamente", opener, onConfirm:async () => { await api(`/planned/${current.id}`, {method:"DELETE"}); toast("Bloco excluído."); }});
  };
}

function openPlanPreview(proposal) {
  let sessions = [...proposal.sessions];
  const draw = () => { const form = modal("Prévia do planejamento", `<p class="muted">Nada foi salvo. Revise, remova blocos e depois aplique.</p>${proposal.skipped_without_goal.length ? `<p class="muted">Sem meta, não entram no plano: ${esc(proposal.skipped_without_goal.join(", "))}.</p>` : ""}<div class="preview-list">${sessions.map((item, index) => `<div class="list-item row"><div><strong>${item.scheduled_date} · ${item.start_time} · ${esc(item.subject_name)}</strong><div class="muted">${esc(item.topic_name || "Sessão")} · ${item.planned_duration_minutes} min · ${esc(item.reason)}</div></div><button type="button" class="button danger" data-remove="${index}">Remover</button></div>`).join("") || empty("Nenhum bloco proposto", "Defina meta semanal e disponibilidade.")}</div>`, async () => { if (sessions.length) await api("/planning/apply", {method:"POST",body:JSON.stringify({sessions})}); });
    $(".button.primary", form).textContent = "Aplicar plano";
    form.querySelectorAll("[data-remove]").forEach(button => button.onclick = () => { sessions.splice(Number(button.dataset.remove), 1); $("#modal-root").replaceChildren(); draw(); });
  }; draw();
}

async function editAvailability(id) {
  const current = (await api("/availability")).find(item => item.id === id);
  if (!current) return toast("Esta faixa não foi encontrada.");
  modal(`Editar disponibilidade de ${weekdays[current.weekday]}`, `<label>Início<input name="start_time" type="time" value="${current.start_time}" required></label><label>Fim<input name="end_time" type="time" value="${current.end_time}" required></label><label><input name="enabled" type="checkbox" value="true" ${current.enabled ? "checked" : ""}> Faixa ativa</label>`, async (values, form) => {
    const data = new FormData(form);
    await api(`/availability/${id}`, {method:"PATCH",body:JSON.stringify({start_time:data.get("start_time"),end_time:data.get("end_time"),enabled:data.get("enabled") === "true"})});
  });
}

function clockMinutes(value) {
  const [hour = 0, minute = 0] = String(value || "00:00").split(":").map(Number);
  return hour * 60 + minute;
}

function calendarDayLabel(value) {
  return new Intl.DateTimeFormat("pt-BR", {timeZone:"UTC", weekday:"short", day:"numeric", month:"short"}).format(value).replace(".", "");
}

function planningTitle(range) {
  if (planningView.mode === "month") return new Intl.DateTimeFormat("pt-BR", {timeZone:"UTC", month:"long", year:"numeric"}).format(planningView.cursor);
  const format = value => new Intl.DateTimeFormat("pt-BR", {timeZone:"UTC", day:"2-digit", month:"short"}).format(value).replace(".", "");
  return `${format(range.first)} — ${format(range.last)}`;
}

function planningBlockSummary(item) {
  return `${item.subject_name || "Matéria"} · ${item.scheduled_date} · ${item.start_time || "horário livre"}`;
}

function planningDaySummary(day) {
  return new Intl.DateTimeFormat("pt-BR", {timeZone:"UTC", weekday:"long", day:"numeric", month:"long", year:"numeric"}).format(calendarDateFromISO(day));
}

let planningDayDeleteDialogOpen = false;

function openPlanningDayDelete(day, count, opener) {
  if (planningDayDeleteDialogOpen || !day || !count) return;
  planningDayDeleteDialogOpen = true;
  const blockLabel = `${count} ${count === 1 ? "bloco planejado" : "blocos planejados"}`;
  confirmAction({
    title:"Excluir planejamento diário",
    message:`Excluir ${blockLabel} em ${planningDaySummary(day)}? Esta ação é definitiva e remove todo o planejamento desse dia.`,
    confirmLabel:"Excluir o dia inteiro",
    opener,
    onConfirm:async () => {
      const result = await api(`/planned/day/${encodeURIComponent(day)}`, {method:"DELETE"});
      const deleted = Number(result?.deleted);
      const amount = Number.isFinite(deleted) ? deleted : count;
      toast(`${amount} ${amount === 1 ? "bloco excluído" : "blocos excluídos"} do planejamento de ${planningDaySummary(day)}.`);
    },
    onClose:() => { planningDayDeleteDialogOpen = false; }
  });
}

async function renderPlanning() {
  const range = planningRange();
  const today = saoPauloTodayISO();
  const [availability, planned, studies, preferences] = await Promise.all([
    api("/availability"),
    api(`/planned?start=${encodeURIComponent(range.start)}&end=${encodeURIComponent(range.end)}`),
    api("/studies"),
    api("/settings")
  ]);
  const availableMinutes = range.dates.reduce((total, date) => {
    const weekday = (date.getUTCDay() + 6) % 7;
    return total + availability.filter(item => Number(item.weekday) === weekday && item.enabled !== 0 && item.enabled !== false).reduce((sum, item) => sum + Math.max(0, clockMinutes(item.end_time) - clockMinutes(item.start_time)), 0);
  }, 0);
  const plannedMinutes = planned.reduce((sum, item) => sum + Number(item.planned_duration_minutes || 0), 0);
  const plannedByDate = planned.reduce((all, item) => {
    const current = all.get(item.scheduled_date) || [];
    current.push(item);
    all.set(item.scheduled_date, current);
    return all;
  }, new Map());
  const periodLabel = planningTitle(range);
  const previousLabel = planningView.mode === "month" ? "Mês anterior" : "Semana anterior";
  const nextLabel = planningView.mode === "month" ? "Próximo mês" : "Próxima semana";
  const monthIndex = planningView.cursor.getUTCMonth();

  app.innerHTML = `<section class="planning-heading"><div><span class="tag">${planningView.mode === "month" ? "VISÃO MENSAL" : "VISÃO SEMANAL"}</span><h2>${esc(periodLabel)}</h2><p class="muted">${range.start} até ${range.end} · clique em um bloco para editar, começar, reagendar, cancelar ou excluir.</p></div><div class="planning-heading-actions"><div class="planning-view-toggle" role="group" aria-label="Visualização do calendário"><button type="button" class="button ${planningView.mode === "month" ? "primary" : "ghost"}" data-planning-mode="month" aria-pressed="${planningView.mode === "month"}">Mês</button><button type="button" class="button ${planningView.mode === "week" ? "primary" : "ghost"}" data-planning-mode="week" aria-pressed="${planningView.mode === "week"}">Semana</button></div><div class="planning-actions"><button class="button ghost" data-availability>Disponibilidade</button><button class="button" data-new-plan>+ Nova sessão</button><button class="button primary" data-generate>Gerar plano</button></div></div></section><div class="planning-navigation" aria-label="Navegação do calendário"><button type="button" class="button ghost" data-planning-nav="previous">← ${previousLabel}</button><button type="button" class="button" data-planning-nav="today">Hoje</button><button type="button" class="button ghost" data-planning-nav="next">${nextLabel} →</button></div><div class="grid kpis">${card("Disponível", hours(availableMinutes * 60), `no intervalo exibido`)}${card("Planejado", hours(plannedMinutes * 60), `${planned.length} bloco(s) no intervalo`)}${card("Com meta", studies.filter(item => item.weekly_goal_minutes).length, "matérias com meta semanal")}${card("Pausa", `${preferences.planning_break_minutes || 10} min`, "minutos entre blocos automáticos")}</div><div class="grid split planning-layout"><section class="card planning-calendar-card"><div class="calendar-weekdays" aria-hidden="true">${["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"].map(day => `<span>${day}</span>`).join("")}</div><div class="planning-calendar" role="grid" aria-label="Calendário de ${esc(periodLabel)}">${range.dates.map(date => {
    const day = calendarISO(date);
    const sessions = plannedByDate.get(day) || [];
    const outsideMonth = date.getUTCMonth() !== monthIndex;
    const dayLabel = calendarDayLabel(date);
    const plannedBlockLabel = `${sessions.length} ${sessions.length === 1 ? "bloco planejado" : "blocos planejados"}`;
    const deleteDay = sessions.length ? `<button type="button" class="button ghost danger calendar-day-delete" data-delete-planning-day="${day}" data-planning-day-count="${sessions.length}" aria-label="Excluir os ${plannedBlockLabel} de ${esc(planningDaySummary(day))}" title="Excluir todos os blocos deste dia">Excluir dia</button>` : "";
    return `<article class="calendar-day ${outsideMonth ? "outside-month" : ""} ${day === today ? "today" : ""}" role="gridcell" aria-label="${esc(dayLabel)}${day === today ? ", hoje" : ""}"><header><div class="calendar-day-date"><time datetime="${day}">${date.getUTCDate()}</time><span>${esc(dayLabel.replace(/^\S+\s*/, ""))}</span></div>${deleteDay}</header><div class="calendar-sessions">${sessions.map(item => `<button type="button" class="session session-block" data-plan="${item.id}" aria-label="Abrir ações para ${esc(planningBlockSummary(item))}"><span class="session-time">${esc(item.start_time || "Livre")}</span><strong>${esc(item.subject_name)}</strong><span class="session-topic">${esc(item.topic_name || "Sessão sem tópico")}</span><span class="session-duration">${item.planned_duration_minutes} min</span></button>`).join("") || `<span class="calendar-free">Dia livre</span>`}</div></article>`;
  }).join("")}</div></section><aside class="stack"><section class="card"><h2>Disponibilidade</h2>${availability.map(item => `<div class="list-item row"><span>${weekdays[item.weekday]} · ${item.start_time}–${item.end_time}</span><span><button class="button ghost" data-edit-availability="${item.id}">Editar</button><button class="button ghost" data-delete-availability="${item.id}">Excluir</button></span></div>`).join("") || empty("Nenhuma faixa", "Adicione horários em que você pode estudar.")}</section><section class="card"><h2>Meta e duração</h2><form id="planning-settings" class="form"><label>Duração padrão <span class="field-help">Minutos por bloco criado no planejamento.</span><input name="default_session_minutes" type="number" min="1" value="${preferences.default_session_minutes || 50}"></label><label>Intervalo padrão <span class="field-help">Minutos de pausa entre blocos gerados automaticamente.</span><input name="planning_break_minutes" type="number" min="0" value="${preferences.planning_break_minutes || 10}"></label><button class="button">Salvar preferências</button></form></section></aside></div>`;

  syncPlanningLocation();
  $("#planning-settings").onsubmit = async event => { event.preventDefault(); const values = fields(event.currentTarget); await api("/settings", {method:"PUT",body:JSON.stringify(values)}); toast("Preferências do planejamento salvas."); render(); };
  app.querySelectorAll("[data-planning-nav]").forEach(button => {
    button.onclick = () => {
      const direction = button.dataset.planningNav;
      if (direction === "today") planningView.cursor = planningView.mode === "month" ? calendarMonthStart(planningToday()) : planningToday();
      else if (planningView.mode === "month") planningView.cursor = calendarAddMonths(planningView.cursor, direction === "previous" ? -1 : 1);
      else planningView.cursor = calendarAddDays(planningView.cursor, direction === "previous" ? -7 : 7);
      syncPlanningLocation();
      render();
    };
  });
  app.querySelectorAll("[data-planning-mode]").forEach(button => {
    button.onclick = () => {
      const nextMode = button.dataset.planningMode;
      if (nextMode === planningView.mode) return;
      planningView.mode = nextMode;
      if (nextMode === "month") planningView.cursor = calendarMonthStart(planningView.cursor);
      syncPlanningLocation();
      render();
    };
  });

  const goals = document.createElement("section");
  goals.className = "card";
  goals.innerHTML = `<h2>Metas semanais</h2><p class="muted">Defina, em minutos por semana, quanto pretende estudar em cada matéria. Só matérias com meta entram no plano automático.</p>${studies.length ? studies.map(study => `<form class="goal-form list-item row" data-study="${study.id}"><div><strong>${esc(study.name)}</strong><div class="muted">${study.weekly_goal_minutes ? `${study.weekly_goal_minutes} min/semana` : "Sem meta — não entra no plano"}</div></div><label class="goal-input">Meta semanal (minutos por semana)<input name="weekly_goal_minutes" type="number" min="1" value="${study.weekly_goal_minutes || ""}" placeholder="ex.: 180" required></label><button class="button" type="submit">Salvar</button></form>`).join("") : empty("Sem matérias", "Crie ou adicione uma matéria antes de definir a meta.")}`;
  $(".planning-layout > aside", app).append(goals);
  goals.querySelectorAll(".goal-form").forEach(form => form.onsubmit = async event => { event.preventDefault(); const value = Number(new FormData(form).get("weekly_goal_minutes")); try { await api(`/studies/${form.dataset.study}`, {method:"PATCH", body:JSON.stringify({weekly_goal_minutes:value})}); toast("Meta semanal atualizada."); render(); } catch (error) { toast(error.message); } });
}

const formationBlockerLabels = [
  ["curriculum_subjects", "disciplina da grade", "disciplinas da grade"],
  ["study_subjects", "estudo", "estudos"],
  ["planned_sessions", "bloco de planejamento", "blocos de planejamento"],
  ["study_sessions", "sessão estudada", "sessões estudadas"],
  ["notes", "anotação", "anotações"],
  ["topics", "tópico", "tópicos"],
  ["reviews", "revisão", "revisões"],
  ["evaluations", "avaliação", "avaliações"]
];

function formationBlockersText(blockers = {}) {
  return formationBlockerLabels.flatMap(([key, singular, plural]) => {
    const count = Number(blockers[key]) || 0;
    return count ? [`${count} ${count === 1 ? singular : plural}`] : [];
  }).join(", ");
}

function formationDeleteError(error) {
  if (error?.code !== "formation_has_dependencies") return error?.message;
  const blockers = formationBlockersText(error.blockers);
  const details = blockers ? ` Vínculos encontrados: ${blockers}.` : "";
  return `${error.message}${details} Apagar dias do planejamento não exclui disciplinas, estudos ou histórico. Use “Arquivar em vez disso” para tirar a formação da lista de ativas sem perder esses dados.`;
}

function curriculumLocalFilter(rows) {
  const query = curriculumView.q.trim().toLocaleLowerCase("pt-BR");
  const selected = rows.filter(row => {
    if (curriculumView.quick !== "archived" && curriculumView.visibility === "active" && curriculumIsArchived(row)) return false;
    if (curriculumView.quick !== "archived" && curriculumView.visibility === "archived" && !curriculumIsArchived(row)) return false;
    if (query && !`${row.name || ""} ${row.code || ""}`.toLocaleLowerCase("pt-BR").includes(query)) return false;
    if (curriculumView.period && String(row.period || "") !== curriculumView.period) return false;
    if (curriculumView.academicStatus && row.academic_status !== curriculumView.academicStatus) return false;
    if (curriculumView.reviewStatus && (row.review_status || "none") !== curriculumView.reviewStatus) return false;
    const review = row.review_status || "none";
    if (curriculumView.quick === "available" && row.academic_status !== "available") return false;
    if (curriculumView.quick === "in_progress" && row.academic_status !== "in_progress") return false;
    if (curriculumView.quick === "review" && review === "none") return false;
    if (curriculumView.quick === "completed" && row.academic_status !== "completed") return false;
    if (curriculumView.quick === "pending" && (isStructuralCurriculum(row) || ["completed", "exempted"].includes(row.academic_status))) return false;
    if (curriculumView.quick === "failed" && row.academic_status !== "failed") return false;
    if (curriculumView.quick === "locked" && row.academic_status !== "locked") return false;
    if (curriculumView.quick === "exempted" && row.academic_status !== "exempted") return false;
    if (curriculumView.quick === "archived" && !curriculumIsArchived(row)) return false;
    return true;
  });
  const ordering = {
    period: (left, right) => String(left.period || "").localeCompare(String(right.period || ""), "pt-BR", {numeric:true}) || count(left.sort_order) - count(right.sort_order) || String(left.name).localeCompare(String(right.name), "pt-BR"),
    order: (left, right) => count(left.sort_order) - count(right.sort_order) || String(left.name).localeCompare(String(right.name), "pt-BR"),
    name: (left, right) => String(left.name).localeCompare(String(right.name), "pt-BR"),
    status: (left, right) => String(left.academic_status).localeCompare(String(right.academic_status)) || String(left.name).localeCompare(String(right.name), "pt-BR"),
    updated: (left, right) => String(right.updated_at || right.created_at || "").localeCompare(String(left.updated_at || left.created_at || "")),
  };
  return selected.sort(ordering[curriculumView.sort] || ordering.period);
}

function curriculumSummary(rows, remoteSummary = {}, formation = {}) {
  const source = remoteSummary.academic_progress || remoteSummary.progress || remoteSummary;
  const read = (...keys) => {
    for (const key of keys) if (source?.[key] !== undefined && source?.[key] !== null) return count(source[key]);
    for (const key of keys) if (formation?.[key] !== undefined && formation?.[key] !== null) return count(formation[key]);
    return null;
  };
  const validRows = rows.filter(row => !curriculumIsArchived(row) && !isStructuralCurriculum(row));
  const completed = read("completed", "completed_count", "completed_subjects") ?? validRows.filter(row => row.academic_status === "completed").length;
  const exempted = read("exempted", "exempted_count", "exempted_subjects") ?? validRows.filter(row => row.academic_status === "exempted").length;
  const inProgress = read("in_progress", "in_progress_count", "in_progress_subjects") ?? validRows.filter(row => row.academic_status === "in_progress").length;
  const review = read("review", "review_count", "review_subjects") ?? validRows.filter(row => (row.review_status || "none") !== "none").length;
  const total = read("total", "total_valid", "valid_subjects", "total_subjects", "curriculum_count") ?? validRows.length;
  const pending = read("pending", "pending_count", "pending_subjects") ?? validRows.filter(row => !["completed", "exempted"].includes(row.academic_status)).length;
  const percent = read("percent", "progress_percent", "academic_progress_percent") ?? (total ? Math.round((completed + exempted) * 100 / total) : 0);
  return {total, completed, exempted, inProgress, pending, review, percent:clampPercent(percent)};
}

function curriculumQuickFilters() {
  const filters = [["all","Todas"],["available","Disponíveis"],["in_progress","Em andamento"],["review","Para revisar"],["completed","Concluídas"],["pending","Pendentes"],["failed","Reprovadas"],["locked","Bloqueadas"],["exempted","Dispensadas"],["archived","Arquivadas"]];
  return `<div class="quick-filter-list" role="group" aria-label="Filtros rápidos">${filters.map(([value, text]) => `<button class="filter-pill ${curriculumView.quick === value ? "active" : ""}" type="button" data-curriculum-quick="${value}" aria-pressed="${curriculumView.quick === value}">${text}</button>`).join("")}</div>`;
}

function curriculumActionsMarkup(row, formation) {
  const formationArchived = Boolean(formation.archived_at);
  if (formationArchived) return `<div class="action-unavailable"><span>Restaure a formação para alterar esta disciplina.</span><button class="button ghost" data-restore-formation="${formation.id}">Restaurar formação</button></div>`;
  const review = row.review_status || "none";
  const reviewAction = review === "none" ? "Marcar para revisar" : review === "reviewed" ? "Reabrir revisão" : "Editar revisão";
  const canAddStudy = !row.active_study_id && ["available", "in_progress"].includes(row.academic_status) && !curriculumIsArchived(row) && !isStructuralCurriculum(row);
  const addStudyReason = isStructuralCurriculum(row) ? "Linha estrutural não pode entrar nos estudos atuais." : curriculumIsArchived(row) ? "Restaure a disciplina antes de adicionar aos estudos." : "A disciplina precisa estar disponível ou em andamento para entrar nos estudos atuais.";
  return `<details class="action-menu"><summary>Ações</summary><div class="action-menu-content"><button class="button" data-curriculum-action="edit" data-curriculum-id="${row.id}">Editar</button><button class="button" data-curriculum-action="status" data-curriculum-id="${row.id}">Alterar estado acadêmico</button><button class="button" data-curriculum-action="review" data-curriculum-id="${row.id}">${reviewAction}</button>${review !== "none" ? `<button class="button ghost" data-curriculum-action="clear-review" data-curriculum-id="${row.id}">Retirar da revisão</button>` : ""}${row.active_study_id ? `<a class="button" href="/studies?study_filter=all&selected=${row.active_study_id}">Abrir estudo vinculado</a><button class="button" data-study-remove-current="${row.active_study_id}">Encerrar estudo vinculado</button>` : canAddStudy ? `<button class="button" data-add-study="${row.id}">Adicionar aos estudos atuais</button>` : `<p class="action-explanation">${esc(addStudyReason)}</p>`}${curriculumIsArchived(row) ? `<button class="button primary" data-curriculum-action="restore" data-curriculum-id="${row.id}">Restaurar disciplina</button>` : `<button class="button" data-curriculum-action="archive" data-curriculum-id="${row.id}">Arquivar disciplina</button>`}<button class="button ghost" data-curriculum-action="dependencies" data-curriculum-id="${row.id}">Consultar dependências</button><button class="button danger" data-curriculum-action="destroy" data-curriculum-id="${row.id}">Excluir definitivamente</button></div></details>`;
}

function curriculumSectionsMarkup(rows) {
  const groups = [
    ["in_progress", "Em andamento", row => row.academic_status === "in_progress"],
    ["review", "Para revisar", row => (row.review_status || "none") !== "none"],
    ["completed", "Concluídas", row => row.academic_status === "completed"],
    ["pending", "Pendentes", row => !isStructuralCurriculum(row) && !["completed", "exempted"].includes(row.academic_status)],
  ];
  return `<section class="curriculum-sections" aria-label="Resumo da grade por situação">${groups.map(([key, title, predicate]) => {
    const items = rows.filter(predicate);
    return `<details class="curriculum-section" ${key === "in_progress" ? "open" : ""}><summary><span>${title}</span><span class="status-count">${items.length}</span></summary>${items.length ? `<ul>${items.slice(0, 6).map(item => `<li><strong>${esc(item.name)}</strong><span>${esc(item.period || "Sem período")} · ${label(item.academic_status)}${(item.review_status || "none") !== "none" ? ` · ${curriculumReviewLabel(item.review_status)}` : ""}</span></li>`).join("")}${items.length > 6 ? `<li class="muted">e mais ${items.length - 6} disciplina(s) na tabela.</li>` : ""}</ul>` : '<p class="muted">Nenhuma disciplina nesta situação com os filtros atuais.</p>'}</details>`;
  }).join("")}</section>`;
}

function curriculumBulkToolbar(formationId, rows) {
  const selected = rows.filter(row => curriculumView.selectedIds.has(row.id));
  return `<section class="bulk-toolbar" aria-label="Ações em lote"><div><strong>${selected.length ? `${selected.length} selecionada(s)` : "Selecione disciplinas"}</strong><span>${selected.length ? "A prévia será mostrada antes da alteração." : "Use as caixas da tabela para aplicar uma ação em lote."}</span></div><label>Estado<select id="curriculum-bulk-status">${curriculumAcademicStatuses.map(value => `<option value="${value}">${label(value)}</option>`).join("")}</select></label><button class="button" data-curriculum-bulk="set_status" ${selected.length ? "" : "disabled"}>Alterar estado</button><label>Revisão<select id="curriculum-bulk-review">${curriculumReviewStatuses.map(value => `<option value="${value}">${curriculumReviewLabel(value)}</option>`).join("")}</select></label><button class="button" data-curriculum-bulk="set_review" ${selected.length ? "" : "disabled"}>Atualizar revisão</button><button class="button" data-curriculum-bulk="archive" ${selected.length ? "" : "disabled"}>Arquivar</button><button class="button" data-curriculum-bulk="restore" ${selected.length ? "" : "disabled"}>Restaurar</button><button class="button danger" data-curriculum-bulk="destroy" ${selected.length ? "" : "disabled"}>Excluir</button></section>`;
}

async function openCurriculumBulkAction(formationId, action) {
  const ids = [...curriculumView.selectedIds];
  if (!ids.length) return toast("Selecione ao menos uma disciplina.");
  const statusInput = $("#curriculum-bulk-status", app);
  const reviewInput = $("#curriculum-bulk-review", app);
  const payload = {ids, action};
  if (action === "set_status") payload.academic_status = statusInput?.value;
  if (action === "set_review") payload.review_status = reviewInput?.value;
  if (action === "classify") payload.item_type = "section";
  const preview = await api(`/formations/${formationId}/curriculum/batch/preview`, {method:"POST", body:JSON.stringify(payload)});
  const isDestroy = action === "destroy";
  const expectedConfirmation = `EXCLUIR ${ids.length} DISCIPLINAS`;
  const labels = {set_status:"Alterar estado acadêmico", set_review:"Atualizar revisão", archive:"Arquivar disciplinas", restore:"Restaurar disciplinas", classify:"Classificar como linha estrutural", destroy:"Excluir disciplinas definitivamente"};
  const form = modal(labels[action] || "Ação em lote", `<p class="muted">Prévia de ${plural(ids.length, "disciplina")}. Nada foi alterado ainda.</p>${dependencySummaryMarkup(preview, "A seleção não possui dependências adicionais.")}${isDestroy ? `<div class="danger-zone"><p><strong>Esta exclusão é definitiva.</strong> Será feito backup e a operação será toda revertida se algo falhar.</p><label>Digite <strong>${expectedConfirmation}</strong> para confirmar<input name="confirmation" autocomplete="off" required></label></div>` : ""}`, async values => {
    if (isDestroy && values.confirmation !== expectedConfirmation) throw new Error(`Digite “${expectedConfirmation}” para confirmar.`);
    await api(`/formations/${formationId}/curriculum/batch`, {method:"POST", body:JSON.stringify({...payload, confirmation:isDestroy ? values.confirmation : undefined, include_dependencies:isDestroy})});
    curriculumView.selectedIds.clear();
  });
  const save = $(".button.primary", form);
  save.textContent = labels[action] || "Confirmar";
  if (isDestroy) { save.classList.remove("primary"); save.classList.add("danger"); window.setTimeout(() => $("[name=confirmation]", form)?.focus(), 0); }
}

function duplicateCandidateRows(candidate) {
  if (Array.isArray(candidate)) return candidate;
  return candidate?.items || candidate?.records || candidate?.candidates || candidate?.subjects || [];
}

async function openDuplicateCandidates(formationId) {
  const payload = await api(`/formations/${formationId}/curriculum/duplicates`);
  const candidates = payload?.groups || payload?.items || payload?.candidates || asRows(payload);
  curriculumView.duplicateCandidates = candidates;
  const form = modal("Revisar possíveis duplicidades", `<p class="muted">Os candidatos pertencem apenas a esta formação e nunca são mesclados automaticamente. Confira os dados e os vínculos antes de escolher o registro principal.</p>${candidates.length ? `<div class="candidate-list">${candidates.map((candidate, index) => { const rows = duplicateCandidateRows(candidate); return `<article><div><strong>${esc(candidate.normalized_name || candidate.key || rows.map(row => row.name).join(" / "))}</strong><span>${rows.map(row => `${esc(row.name)} · ${formatMinutesAsHours(row.workload_minutes)}`).join("<br>")}</span></div><button class="button" type="button" data-open-duplicate-candidate="${index}" data-formation-id="${formationId}">Resolver</button></article>`; }).join("")}</div>` : empty("Nenhuma possível duplicidade", "Não foram encontrados pares candidatos nesta formação.")}`, null);
  $(".button.primary", form)?.remove();
  $(".form-actions", form)?.insertAdjacentHTML("beforeend", '<button class="button primary" type="button" data-close>Fechar</button>');
}

function openDuplicateMerge(formationId, candidate) {
  const rows = duplicateCandidateRows(candidate);
  if (rows.length < 2) return toast("Este candidato não possui registros suficientes para uma mesclagem.");
  const fieldsToPreserve = [["code","Código"],["period","Período / módulo"],["workload_minutes","Carga horária"],["academic_status","Estado acadêmico"],["review_status","Revisão"]];
  const primary = rows[0];
  const form = modal("Mesclar registros candidatos", `<p class="muted">Escolha o registro principal e, para cada campo, qual informação manter. Todos os demais registros deste grupo serão integrados somente após a confirmação e a validação do servidor.</p><fieldset class="choice-list"><legend>Registro principal</legend>${rows.map((row, index) => `<label><input type="radio" name="primary_id" value="${row.id}" ${index === 0 ? "checked" : ""}> <strong>${esc(row.name)}</strong><span>${esc(row.code || "Sem código")} · ${esc(row.period || "Sem período")} · ${formatMinutesAsHours(row.workload_minutes)} · ${label(row.academic_status)}</span></label>`).join("")}</fieldset><label>Nome limpo da disciplina<input name="clean_name" value="${esc(candidate.clean_name || primary.clean_name || primary.name)}" required></label><fieldset class="preserve-fields"><legend>Preservar campo a campo</legend>${fieldsToPreserve.map(([field, title]) => `<label>${title}<select name="preserve_${field}">${rows.map(row => `<option value="${row.id}">${esc(row.name)} — ${esc(field === "workload_minutes" ? formatMinutesAsHours(row[field]) : field === "academic_status" ? label(row[field]) : field === "review_status" ? curriculumReviewLabel(row[field]) : row[field] || "—")}</option>`).join("")}</select></label>`).join("")}</fieldset><label>Digite exatamente <strong data-merge-confirmation>${esc(primary.name)}</strong> para confirmar<input name="confirmation" required autocomplete="off"></label>`, async (values) => {
    const chosenPrimary = rows.find(row => row.id === Number(values.primary_id));
    if (!chosenPrimary) throw new Error("Escolha um registro principal.");
    if (values.confirmation !== chosenPrimary.name) throw new Error("Digite o nome do registro principal exatamente como mostrado.");
    const preserve = {name:values.clean_name};
    fieldsToPreserve.forEach(([field]) => {
      const source = rows.find(row => row.id === Number(values[`preserve_${field}`]));
      preserve[field] = source?.[field] ?? null;
    });
    const duplicateIds = rows.map(row => row.id).filter(id => id !== chosenPrimary.id);
    await api(`/formations/${formationId}/curriculum/merge`, {method:"POST", body:JSON.stringify({primary_id:chosenPrimary.id, duplicate_ids:duplicateIds, preserve, confirmation:values.confirmation})});
  });
  $(".button.primary", form).textContent = "Mesclar registros";
  const updateConfirmation = () => {
    const chosen = rows.find(row => row.id === Number($("[name=primary_id]:checked", form)?.value));
    $("[data-merge-confirmation]", form).textContent = chosen?.name || primary.name;
  };
  form.querySelectorAll("[name=primary_id]").forEach(input => input.addEventListener("change", updateConfirmation));
}

async function openStructuralCandidates(formationId) {
  const payload = await api(`/formations/${formationId}/curriculum/structural-candidates`);
  const candidates = payload?.items || payload?.candidates || asRows(payload);
  const form = modal("Linhas estruturais importadas", `<p class="muted">Estas linhas parecem cabeçalhos de período/módulo, não disciplinas. Classificá-las como estruturais as retira do cálculo de progresso sem apagar dados.</p>${candidates.length ? `<div class="candidate-list">${candidates.map(row => `<article><div><strong>${esc(row.name)}</strong><span>${esc(row.period || "Sem período")} · ${label(row.academic_status)} · ${formatMinutesAsHours(row.workload_minutes)}</span></div><button class="button" type="button" data-classify-structural="${row.id}" data-formation-id="${formationId}">Classificar como estrutural</button></article>`).join("")}</div>` : empty("Nenhuma linha estrutural candidata", "Não há linhas que precisem ser classificadas nesta formação.")}`, null);
  $(".button.primary", form)?.remove();
  $(".form-actions", form)?.insertAdjacentHTML("beforeend", '<button class="button primary" type="button" data-close>Fechar</button>');
}

async function renderFormations() {
  const renderRevision = ++formationRenderRevision;
  const formations = await api(`/formations?state=${formationView.filter}`);
  let selected = formations.find(item => item.id === formationView.selectedId) || formations[0] || null;
  formationView.selectedId = selected?.id || null;
  if (curriculumView.formationId !== selected?.id) {
    curriculumView.formationId = selected?.id || null;
    curriculumView.selectedIds.clear();
  }
  syncFormationLocation();

  const draw = async () => {
    const requestedSelection = selected;
    const parameters = new URLSearchParams({visibility:curriculumView.visibility, q:curriculumView.q, period:curriculumView.period, academic_status:curriculumView.academicStatus, review_status:curriculumView.reviewStatus, quick:curriculumView.quick, sort:curriculumView.sort});
    const management = requestedSelection ? await api(`/formations/${requestedSelection.id}/curriculum/management?${parameters}`) : {items:[], summary:{}, periods:[]};
    if (renderRevision !== formationRenderRevision || requestedSelection?.id !== selected?.id) return;
    const allRows = asRows(management);
    const rows = curriculumLocalFilter(allRows);
    curriculumView.rows = allRows;
    const periods = management?.periods || [...new Set(allRows.map(row => row.period).filter(Boolean))].sort((left, right) => String(left).localeCompare(String(right), "pt-BR", {numeric:true}));
    const summary = curriculumSummary(allRows, management?.summary, management?.formation || selected);
    const periodSummary = management?.summary?.by_period || [];
    const isArchived = Boolean(selected?.archived_at);
    const knownDependencies = formationBlockersText({curriculum_subjects:selected?.curriculum_count, study_subjects:selected?.active_studies});
    const progressCards = `<section class="academic-progress"><div class="academic-progress-heading"><div><span class="tag">PROGRESSO ACADÊMICO</span><h3>${summary.percent}% concluído</h3><p>Concluídas e dispensadas contam para a grade; revisão é um indicador separado.</p></div><strong>${summary.completed + summary.exempted}/${summary.total}</strong></div><div class="progress progress-large" aria-label="${summary.percent}% do currículo concluído"><i style="width:${summary.percent}%"></i></div><div class="academic-metrics"><span><strong>${summary.completed}</strong> concluídas</span><span><strong>${summary.exempted}</strong> dispensadas</span><span><strong>${summary.inProgress}</strong> em andamento</span><span><strong>${summary.pending}</strong> pendentes</span><span><strong>${summary.review}</strong> para revisar</span></div>${periodSummary.length ? `<details class="period-progress" open><summary>Progresso por período / módulo</summary><div>${periodSummary.map(period => `<article><div class="row"><strong>${esc(period.period)}</strong><span>${clampPercent(period.academic_progress_percent)}%</span></div><div class="progress"><i style="width:${clampPercent(period.academic_progress_percent)}%"></i></div><span>${period.completed + period.exempted}/${period.total_subjects} concluídas ou dispensadas · ${period.pending} pendentes · ${period.review} para revisar</span></article>`).join("")}</div></details>` : ""}</section>`;
    const curriculumActions = isArchived ? `<div class="action-unavailable"><span>Restaure a formação para alterar a grade.</span><button class="button primary" data-restore-formation="${selected.id}">Restaurar formação</button></div>` : `<div class="action-group"><button class="button" data-add-subject>+ Adicionar disciplina</button><button class="button ghost" data-import>Importar grade</button><button class="button ghost" data-open-duplicate-review="${selected.id}">Revisar duplicidades</button><button class="button ghost" data-open-structural-candidates="${selected.id}">Linhas estruturais</button></div>`;
    app.innerHTML = `<div class="bar"><div><label class="inline-filter">Mostrar <select id="formation-filter"><option value="active" ${formationView.filter === "active" ? "selected" : ""}>Ativas</option><option value="archived" ${formationView.filter === "archived" ? "selected" : ""}>Arquivadas</option><option value="all" ${formationView.filter === "all" ? "selected" : ""}>Todas</option></select></label><span class="muted">${formations.length} formação(ões)</span></div><button class="button primary" data-new-formation>Nova formação</button></div><div class="grid formation-layout"><aside class="stack">${formations.map(item => { const progress = curriculumSummary([], item.academic_progress || item.progress || item, item); return `<article class="card formation-select ${item.id === selected?.id ? "selected" : ""}" data-formation="${item.id}" data-select-formation="${item.id}" role="button" aria-label="Selecionar ${esc(item.name)}${item.id === selected?.id ? " (selecionada)" : ""}" tabindex="0"><div class="row"><div><strong>${esc(item.name)}</strong><div class="muted">${esc(item.institution || "Instituição não informada")}</div><div class="muted">${item.curriculum_count ?? progress.total} disciplina(s) · ${item.active_studies || 0} estudo(s) ativo(s)</div><div class="mini-progress"><i style="width:${progress.percent}%"></i><span>${progress.percent}% acadêmico</span></div></div><span class="status">${label(item.status)}</span></div></article>`; }).join("") || empty("Nenhuma formação nesta lista", formationView.filter === "archived" ? "Não há formações arquivadas." : "Crie uma formação para montar sua grade.")}</aside><section class="stack">${selected ? `<section class="card"><div class="bar"><div><h2>${esc(selected.name)}</h2><p class="muted">${esc(selected.institution || "Instituição não informada")} · ${esc(selected.modality || "Modalidade não informada")}</p></div><div class="action-group">${isArchived ? `<button class="button primary" data-restore-formation="${selected.id}">Restaurar</button>` : `<button class="button" data-edit-formation="${selected.id}">Editar formação</button><button class="button" data-archive-formation="${selected.id}">Arquivar</button>`}<button class="button ghost" data-formation-dependencies="${selected.id}">Dependências</button><button class="button danger" data-delete-formation="${selected.id}">Excluir</button></div></div><div class="formation-details"><span class="tag">Prioridade de foco ${selected.focus_priority}/5</span>${selected.start_date || selected.expected_end_date ? `<span class="muted">${esc(selected.start_date || "—")} → ${esc(selected.expected_end_date || "—")}</span>` : ""}</div>${progressCards}${knownDependencies ? `<p class="formation-delete-hint" role="status"><strong>A exclusão definitiva exige confirmação.</strong> Esta formação possui ${knownDependencies}. Consulte as dependências para ver a prévia completa ou use Arquivar para preservar o histórico.</p>` : ""}</section><section class="card curriculum-management"><div class="bar"><div><span class="tag">CENTRAL DE DISCIPLINAS</span><h2>Grade curricular</h2><p class="muted">${rows.length} resultado(s) de ${allRows.length}. Filtros e progresso usam as informações devolvidas pelo servidor.</p></div>${curriculumActions}</div><section class="curriculum-controls" aria-label="Filtros da grade"><label>Pesquisar<input id="curriculum-q" value="${esc(curriculumView.q)}" placeholder="Nome ou código"></label><label>Período / módulo<select id="curriculum-period"><option value="">Todos</option>${periods.map(value => `<option value="${esc(value)}" ${curriculumView.period === value ? "selected" : ""}>${esc(value)}</option>`).join("")}</select></label><label>Estado acadêmico<select id="curriculum-status"><option value="">Todos</option>${curriculumAcademicStatuses.map(value => `<option value="${value}" ${curriculumView.academicStatus === value ? "selected" : ""}>${label(value)}</option>`).join("")}</select></label><label>Revisão<select id="curriculum-review"><option value="">Todas</option>${curriculumReviewStatuses.map(value => `<option value="${value}" ${curriculumView.reviewStatus === value ? "selected" : ""}>${curriculumReviewLabel(value)}</option>`).join("")}</select></label><label>Visibilidade<select id="curriculum-visibility"><option value="active" ${curriculumView.visibility === "active" ? "selected" : ""}>Ativas</option><option value="archived" ${curriculumView.visibility === "archived" ? "selected" : ""}>Arquivadas</option><option value="all" ${curriculumView.visibility === "all" ? "selected" : ""}>Todas</option></select></label><label>Ordenar<select id="curriculum-sort"><option value="period" ${curriculumView.sort === "period" ? "selected" : ""}>Período</option><option value="order" ${curriculumView.sort === "order" ? "selected" : ""}>Ordem</option><option value="name" ${curriculumView.sort === "name" ? "selected" : ""}>Nome</option><option value="status" ${curriculumView.sort === "status" ? "selected" : ""}>Status</option><option value="updated" ${curriculumView.sort === "updated" ? "selected" : ""}>Atualização</option></select></label></section>${curriculumQuickFilters()}${curriculumBulkToolbar(selected.id, rows)}${curriculumSectionsMarkup(rows)}<div class="table-wrap"><table class="table curriculum-table"><thead><tr><th><label class="select-all-label"><input id="curriculum-select-all" type="checkbox" ${rows.length && rows.every(row => curriculumView.selectedIds.has(row.id)) ? "checked" : ""} aria-label="Selecionar todas as disciplinas visíveis"> Selecionar</label></th><th>Disciplina</th><th>Período</th><th>Estado acadêmico</th><th>Revisão</th><th>Atualização</th><th>Ações</th></tr></thead><tbody>${rows.map(row => `<tr class="${curriculumIsArchived(row) ? "is-archived" : ""} ${isStructuralCurriculum(row) ? "is-structural" : ""}"><td><input type="checkbox" data-curriculum-select="${row.id}" ${curriculumView.selectedIds.has(row.id) ? "checked" : ""} aria-label="Selecionar ${esc(row.name)}"></td><td><strong>${esc(row.name)}</strong><div class="muted">${isStructuralCurriculum(row) ? "Linha estrutural · " : ""}${esc(row.code || "Sem código")} · ${formatMinutesAsHours(row.workload_minutes)} · ordem ${row.sort_order ?? 0}</div></td><td>${esc(row.period || "—")}</td><td><span class="status status-${esc(row.academic_status)}">${label(row.academic_status)}</span></td><td><span class="review-status ${row.review_status || "none"}">${curriculumReviewLabel(row.review_status)}</span>${row.review_priority ? `<div class="muted">prioridade ${row.review_priority}/5</div>` : ""}</td><td class="muted">${esc(row.updated_at || row.created_at || "—")}</td><td>${curriculumActionsMarkup(row, selected)}</td></tr>`).join("") || `<tr><td colspan="7">${empty("Nenhuma disciplina encontrada", "Ajuste os filtros ou cadastre uma nova disciplina.")}</td></tr>`}</tbody></table></div></section>` : empty("Selecione uma formação", "Escolha um cartão à esquerda ou crie uma nova formação.")}</section></div>`;
    $("#formation-filter", app).onchange = event => { formationView.filter = event.target.value; formationView.selectedId = null; syncFormationLocation(); render(); };
    const controlMap = [["#curriculum-q", "q"], ["#curriculum-period", "period"], ["#curriculum-status", "academicStatus"], ["#curriculum-review", "reviewStatus"], ["#curriculum-visibility", "visibility"], ["#curriculum-sort", "sort"]];
    controlMap.forEach(([selector, key]) => $(selector, app)?.addEventListener(key === "q" ? "input" : "change", event => { curriculumView[key] = event.target.value; if (key === "q") { window.clearTimeout(curriculumView.queryTimer); curriculumView.queryTimer = window.setTimeout(() => draw(), 220); } else draw(); }));
    app.querySelectorAll("[data-curriculum-quick]").forEach(button => button.addEventListener("click", () => {
      const nextQuick = button.dataset.curriculumQuick;
      if (nextQuick === "archived") curriculumView.visibility = "archived";
      else if (curriculumView.quick === "archived" && curriculumView.visibility === "archived") curriculumView.visibility = "active";
      curriculumView.quick = nextQuick;
      draw();
    }));
    $("#curriculum-select-all", app)?.addEventListener("change", event => { rows.forEach(row => event.target.checked ? curriculumView.selectedIds.add(row.id) : curriculumView.selectedIds.delete(row.id)); draw(); });
    app.querySelectorAll("[data-curriculum-select]").forEach(input => input.addEventListener("change", event => { const id = Number(event.target.dataset.curriculumSelect); event.target.checked ? curriculumView.selectedIds.add(id) : curriculumView.selectedIds.delete(id); draw(); }));
    app.querySelectorAll("[data-select-formation]").forEach(card => {
      const select = () => { selected = formations.find(item => item.id === Number(card.dataset.selectFormation)); formationView.selectedId = selected?.id || null; curriculumView.formationId = selected?.id || null; curriculumView.selectedIds.clear(); syncFormationLocation(); draw(); };
      card.onclick = event => { if (!event.target.closest("button, a, input, select")) select(); };
      card.onkeydown = event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); } };
    });
  };
  await draw();
}

function formationEditor(current = null) {
  const isNew = !current;
  const statusField = current?.archived_at ? `<p class="muted">Restaure esta formação para alterar o status.</p>` : `<label>Status<select name="status">${["active", "paused", "completed", "cancelled"].map(item => `<option value="${item}" ${item === current?.status ? "selected" : ""}>${label(item)}</option>`).join("")}</select></label>`;
  const form = modal(isNew ? "Nova formação" : "Editar formação", `<label>Nome<input name="name" value="${esc(current?.name || "")}" required></label><label>Instituição<input name="institution" value="${esc(current?.institution || "")}"></label><label>Modalidade<input name="modality" value="${esc(current?.modality || "")}" placeholder="Presencial, EAD, híbrida…"></label><label>Data de início<input name="start_date" type="date" value="${esc(current?.start_date || "")}"></label><label>Previsão de conclusão<input name="expected_end_date" type="date" value="${esc(current?.expected_end_date || "")}"></label>${statusField}<label>Prioridade de foco (1 a 5)<input name="focus_priority" type="number" min="1" max="5" value="${current?.focus_priority || 3}" required></label>`, async values => {
    const payload = {...values, focus_priority: Number(values.focus_priority)};
    const saved = isNew ? await api("/formations", {method:"POST", body:JSON.stringify(payload)}) : await api(`/formations/${current.id}`, {method:"PATCH", body:JSON.stringify(payload)});
    formationView.filter = saved.archived_at ? "archived" : "active";
    formationView.selectedId = saved.id;
    syncFormationLocation();
  });
  window.setTimeout(() => $("[name=name]", form)?.focus(), 0);
  return form;
}

function curriculumEditor(formationId, current = null) { modal(current ? "Editar disciplina" : "Adicionar disciplina", `<label>Nome<input name="name" value="${esc(current?.name || "")}" required></label><label>Código<input name="code" value="${esc(current?.code || "")}"></label><label>Período / módulo<input name="period" value="${esc(current?.period || "")}"></label><label>Carga horária (min)<input name="workload_minutes" type="number" min="1" value="${current?.workload_minutes || ""}"></label><label>Ordem<input name="sort_order" type="number" min="0" value="${current?.sort_order || 0}"></label><label>Status<select name="academic_status">${["not_available","available","in_progress","completed","failed","locked","exempted"].map(key => `<option value="${key}" ${key===current?.academic_status?"selected":""}>${label(key)}</option>`).join("")}</select></label>`, async values => { values.workload_minutes = values.workload_minutes ? Number(values.workload_minutes) : null; values.sort_order = Number(values.sort_order); if (current) await api(`/curriculum/${current.id}`,{method:"PATCH",body:JSON.stringify(values)}); else await api(`/formations/${formationId}/curriculum`,{method:"POST",body:JSON.stringify(values)}); }); }

const curriculumImportStatuses = ["not_available", "available", "in_progress", "completed", "failed", "locked", "exempted"];

function importClean(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function importMessages(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value.flatMap(importMessages);
  if (typeof value === "object") {
    if (value.message || value.text || value.warning) return [importClean(value.message || value.text || value.warning)];
    return Object.entries(value).map(([field, detail]) => `${field}: ${importClean(detail)}`);
  }
  return [importClean(value)];
}

function importWorkloadMinutes(value) {
  const minutes = Number(value);
  return Number.isFinite(minutes) && minutes > 0 ? Math.round(minutes) : null;
}

function importWorkloadHours(minutes) {
  return minutes ? String(Number((minutes / 60).toFixed(2))) : "";
}

function importWorkloadLabel(minutes) {
  if (!minutes) return "Sem carga horária informada";
  return `${(minutes / 60).toLocaleString("pt-BR", {maximumFractionDigits:2})} h = ${minutes} min`;
}

function importNameKey(value) {
  return importClean(value).toLocaleLowerCase("pt-BR");
}

function importErrorFields(message) {
  const text = importClean(message).toLocaleLowerCase("pt-BR");
  const fields = new Set();
  if (/(disciplina|nome)/.test(text)) fields.add("name");
  if (/(status|situacao|situação)/.test(text)) fields.add("academic_status");
  if (/(carga|hora|minuto)/.test(text)) fields.add("workload_hours");
  if (/(ordem|sequencia|sequência|posicao|posição)/.test(text)) fields.add("sort_order");
  if (/(data de inicio|data de início)/.test(text)) fields.add("start_date");
  if (/(data de termino|data de término)/.test(text)) fields.add("end_date");
  if (/(termino.*anterior|término.*anterior|inicio.*termino|início.*término)/.test(text)) {
    fields.add("start_date");
    fields.add("end_date");
  }
  return fields;
}

function importSortOrder(value) {
  const text = importClean(value);
  if (!text) return null;
  const order = Number(text);
  return Number.isInteger(order) && order >= 0 ? order : null;
}

function importClientErrors(row) {
  const errors = [];
  if (!importClean(row.name)) errors.push("Informe o nome da disciplina.");
  if (!curriculumImportStatuses.includes(row.academic_status)) errors.push("Escolha um status válido antes de importar esta linha.");
  const rawOrder = importClean(row.sort_order);
  if (rawOrder && importSortOrder(rawOrder) === null) errors.push("Ordem deve ser um número inteiro igual ou maior que zero.");
  if (row.start_date && row.end_date && row.start_date > row.end_date) errors.push("A data de término não pode ser anterior à data de início.");
  return errors;
}

function clearImportErrorsForField(row, field) {
  if (!new Set(["name", "academic_status", "workload_hours", "sort_order", "start_date", "end_date"]).has(field)) return;
  row.baseErrors = row.baseErrors.filter(message => !importErrorFields(message).has(field));
}

function importConfidenceLabel(value) {
  const confidence = importClean(value).toLocaleLowerCase("pt-BR");
  return ({high:"alta", medium:"média", low:"baixa"}[confidence] || importClean(value));
}

function normalizeImportPreview(payload) {
  const items = Array.isArray(payload) ? payload : (payload?.items || payload?.subjects || []);
  return {
    rows: items.map((item, index) => {
      const hasAcademicStatus = Object.prototype.hasOwnProperty.call(item || {}, "academic_status");
      const sourceStatus = importClean(hasAcademicStatus ? item?.academic_status : item?.status);
      const validStatus = curriculumImportStatuses.includes(sourceStatus);
      const warnings = importMessages(item?.warnings ?? item?.warning ?? item?.status_warning);
      const blockingErrors = importMessages(item?.blocking_errors ?? item?.errors ?? item?.validation_errors);
      const hasStatusError = blockingErrors.some(message => importErrorFields(message).has("academic_status"));
      if (!validStatus && !hasStatusError) blockingErrors.push(sourceStatus ? `Status “${sourceStatus}” não reconhecido; escolha um status válido antes de importar esta linha.` : "Escolha um status válido antes de importar esta linha.");
      const minutes = importWorkloadMinutes(item?.workload_minutes ?? item?.minutes) ?? (Number(item?.workload_hours ?? item?.hours) > 0 ? Math.round(Number(item.workload_hours ?? item.hours) * 60) : null);
      return {
        source_index: item?.source_index ?? item?.source_row ?? item?.row ?? index + 1,
        source: importClean(item?.source ?? payload?.source ?? payload?.source_label) || null,
        confidence: importClean(item?.confidence ?? item?.extraction_confidence ?? item?.confidence_level) || null,
        status_raw: importClean(item?.status_raw ?? item?.raw_status ?? (!hasAcademicStatus ? item?.status : null)) || null,
        requires_review: Boolean(item?.requires_review),
        name: importClean(item?.name),
        code: importClean(item?.code) || null,
        period: importClean(item?.period) || null,
        workload_minutes: minutes,
        academic_status: validStatus ? sourceStatus : null,
        start_date: importClean(item?.start_date ?? item?.start ?? item?.inicio) || null,
        end_date: importClean(item?.end_date ?? item?.end ?? item?.termino ?? item?.término) || null,
        notes: importClean(item?.notes ?? item?.observations ?? item?.observacoes ?? item?.observações) || null,
        sort_order: Number.isFinite(Number(item?.sort_order)) && Number(item.sort_order) >= 0 ? Number(item.sort_order) : index,
        aliases: importMessages(item?.aliases ?? item?.alias_mappings ?? item?.recognized_aliases),
        baseWarnings: [...new Set(warnings.filter(Boolean))],
        baseErrors: [...new Set(blockingErrors.filter(Boolean))],
        warnings: [],
        errors: [],
        serverBlockedWithoutDetails: Boolean(item?.blocked || item?.has_blocking_error) && !blockingErrors.length,
        blocked: false,
        serverDuplicate: Boolean(item?.duplicate || item?.is_duplicate || item?.existing_duplicate || item?.duplicate_in_file),
        duplicate: false,
        duplicate_action: ["skip", "update", "keep_both"].includes(item?.duplicate_action) ? item.duplicate_action : "skip",
        include: item?.include !== false
      };
    }),
    summary: payload?.summary || null,
    warnings: importMessages(payload?.warnings),
    sheets: payload?.sheets || [],
    selected_sheet: payload?.selected_sheet ?? null,
    source: importClean(payload?.source || payload?.source_label || "")
  };
}

function importSheetEntries(sheets) {
  return (Array.isArray(sheets) ? sheets : []).map(sheet => {
    const value = importClean(typeof sheet === "object" ? sheet.id ?? sheet.name ?? sheet.value : sheet);
    const labelText = importClean(typeof sheet === "object" ? sheet.label ?? sheet.name ?? sheet.id : sheet);
    return value ? {value, label:labelText || value} : null;
  }).filter(Boolean);
}

function refreshImportDuplicates(rows, existingNames) {
  const seen = new Set();
  rows.forEach(row => {
    row.warnings = [...row.baseWarnings];
    row.errors = [...row.baseErrors];
    if (row.serverBlockedWithoutDetails) row.errors.push("A origem marcou esta linha para revisão. Corrija os campos indicados ou desmarque a linha.");
    row.errors.push(...importClientErrors(row));
    row.errors = [...new Set(row.errors.filter(Boolean))];
    row.blocked = Boolean(row.errors.length);
    const key = importNameKey(row.name);
    row.duplicate = Boolean(row.serverDuplicate);
    if (!key) {
      row.include = false;
      return;
    }
    if (existingNames.has(key)) {
      row.duplicate = true;
      row.warnings.push("Já existe uma disciplina com este nome nesta formação.");
    } else if (seen.has(key)) {
      row.duplicate = true;
      row.warnings.push("Nome repetido nesta prévia.");
    }
    seen.add(key);
    if (row.duplicate && !["skip", "update", "keep_both"].includes(row.duplicate_action)) row.duplicate_action = "skip";
  });
}

function importPreviewDetails(preview) {
  const details = [];
  const summary = preview.summary;
  if (summary && typeof summary === "object") {
    const summaryFields = [
      ["recognized", "reconhecida(s)"],
      ["selected", "selecionada(s)"],
      ["valid", "pronta(s)"],
      ["with_warnings", "com aviso"],
      ["blocked", "com erro"],
      ["duplicates", "duplicada(s)"]
    ];
    let foundImportSummary = false;
    summaryFields.forEach(([key, text]) => {
      const value = Number(summary[key]);
      if (Number.isFinite(value) && value >= 0) {
        details.push(`${value} ${text}`);
        foundImportSummary = true;
      }
    });
    const totalHours = Number(summary.total_hours);
    if (Number.isFinite(totalHours) && totalHours >= 0) {
      details.push(`${totalHours.toLocaleString("pt-BR", {maximumFractionDigits:2})} h identificadas`);
      foundImportSummary = true;
    }
    if (!foundImportSummary) {
      const received = Number(summary.received ?? summary.total ?? summary.rows);
      const ignored = Number(summary.ignored ?? summary.skipped);
      if (Number.isFinite(received) && received >= 0) details.push(`${received} linha(s) lida(s)`);
      if (Number.isFinite(ignored) && ignored > 0) details.push(`${ignored} linha(s) ignorada(s) na leitura`);
    }
    if (summary.message) details.push(importClean(summary.message));
  } else if (summary) details.push(...importMessages(summary));
  if (preview.source) details.push(`origem: ${preview.source}`);
  if (preview.selected_sheet) details.push(`planilha: ${preview.selected_sheet}`);
  return details.filter(Boolean).join(" · ");
}

function importReviewRowMarkup(row, index) {
  const feedback = [...row.aliases.map(alias => `Campo reconhecido: ${alias}.`), ...row.warnings];
  const warnings = feedback.length ? `<ul class="import-row-warnings">${feedback.map(message => `<li>${esc(message)}</li>`).join("")}</ul>` : "";
  const errors = row.errors.length ? `<ul class="import-row-errors" role="alert">${row.errors.map(message => `<li>${esc(message)}</li>`).join("")}</ul>` : "";
  const provenance = [row.source ? `Origem: ${row.source}` : "", row.confidence ? `confiança de extração: ${importConfidenceLabel(row.confidence)}` : "", row.status_raw && row.status_raw !== row.academic_status ? `status original: ${row.status_raw}` : "", row.requires_review ? "revisão necessária" : ""].filter(Boolean).join(" · ");
  const statusOptions = `<option value="" disabled ${row.academic_status ? "" : "selected"}>Selecione o status</option>${curriculumImportStatuses.map(key => `<option value="${key}" ${key === row.academic_status ? "selected" : ""}>${label(key)}</option>`).join("")}`;
  const duplicateChoice = row.duplicate ? `<label class="import-duplicate-choice">Ao encontrar duplicata<select data-import-field="duplicate_action" data-import-index="${index}"><option value="skip" ${row.duplicate_action === "skip" ? "selected" : ""}>Não importar esta linha (seguro)</option><option value="update" ${row.duplicate_action === "update" ? "selected" : ""}>Atualizar a disciplina existente</option><option value="keep_both" ${row.duplicate_action === "keep_both" ? "selected" : ""}>Manter ambas (renomeie antes)</option></select></label>` : "";
  return `<fieldset class="import-row import-review-row ${row.include ? "" : "is-excluded"} ${row.blocked ? "has-errors" : ""}"><legend>Linha ${esc(String(row.source_index || index + 1))} · ${esc(row.name || "Nova disciplina")}</legend>${provenance ? `<p class="import-row-provenance">${esc(provenance)}</p>` : ""}<label class="import-include"><input type="checkbox" data-import-include="${index}" ${row.include ? "checked" : ""}> Incluir na confirmação</label><div class="import-row-fields"><label>Nome<input data-import-field="name" data-import-index="${index}" value="${esc(row.name)}" required></label><label>Código<input data-import-field="code" data-import-index="${index}" value="${esc(row.code || "")}"></label><label>Período / módulo<input data-import-field="period" data-import-index="${index}" value="${esc(row.period || "")}"></label><label>Carga horária (h)<input data-import-field="workload_hours" data-import-index="${index}" type="number" min="0" step="0.25" value="${importWorkloadHours(row.workload_minutes)}"></label><label>Status<select data-import-field="academic_status" data-import-index="${index}">${statusOptions}</select></label><label>Ordem<input data-import-field="sort_order" data-import-index="${index}" type="number" min="0" step="1" value="${esc(row.sort_order ?? "")}"></label><label>Data de início<input data-import-field="start_date" data-import-index="${index}" type="date" value="${esc(row.start_date || "")}"></label><label>Data de término<input data-import-field="end_date" data-import-index="${index}" type="date" value="${esc(row.end_date || "")}"></label><label class="import-row-notes">Observações<textarea data-import-field="notes" data-import-index="${index}" rows="2">${esc(row.notes || "")}</textarea></label></div><div class="import-row-footer"><span data-import-workload="${index}">${importWorkloadLabel(row.workload_minutes)}</span><button type="button" class="button ghost danger" data-import-drop="${index}">Remover da prévia</button></div>${duplicateChoice}${errors}${warnings}</fieldset>`;
}

function updateImportReviewSummary(form, rows) {
  const selected = rows.filter(row => row.include);
  const changes = selected.filter(row => !row.duplicate || row.duplicate_action !== "skip").length;
  const skipped = selected.filter(row => row.duplicate && row.duplicate_action === "skip").length;
  const blocked = selected.filter(row => row.blocked).length;
  const summary = $("[data-import-selection-summary]", form);
  if (summary) summary.textContent = blocked ? `Corrija ou desmarque ${blocked} linha(s) com erro` : `${changes} para adicionar/atualizar · ${skipped} duplicada(s) para ignorar`;
  const submit = $(".button.primary", form);
  if (submit) {
    submit.textContent = `Confirmar importação de ${selected.length} linha(s)`;
    submit.disabled = Boolean(blocked);
  }
}

function importResultMessage(result) {
  const inserted = Array.isArray(result?.inserted) ? result.inserted.length : Number(result?.inserted ?? result?.created ?? 0);
  const updated = Array.isArray(result?.updated) ? result.updated.length : Number(result?.updated || 0);
  const skipped = Array.isArray(result?.skipped) ? result.skipped.length : Number(result?.skipped ?? result?.duplicates ?? 0);
  const parts = [`${Number.isFinite(inserted) ? inserted : 0} adicionada(s)`];
  if (Number.isFinite(updated) && updated) parts.push(`${updated} atualizada(s)`);
  if (Number.isFinite(skipped) && skipped) parts.push(`${skipped} ignorada(s) sem duplicar`);
  return `Importação concluída: ${parts.join(" · ")}.`;
}

function openCurriculumImportReview(formationId, preview, existingNames, opener) {
  const rows = preview.rows;
  const draw = () => {
    const details = importPreviewDetails(preview);
    const topWarnings = preview.warnings.length ? `<ul class="import-top-warnings">${preview.warnings.map(message => `<li>${esc(message)}</li>`).join("")}</ul>` : "";
    const form = modal("Revisar importação da grade", `<p class="muted">A prévia ainda não altera sua formação. Revise as linhas e confirme apenas quando estiver pronto.</p>${details ? `<p class="import-source-info">${esc(details)}</p>` : ""}${topWarnings}<div class="import-review-summary" aria-live="polite"><strong data-import-selection-summary></strong><span>Carga em horas será salva em minutos.</span></div><div id="import-rows" class="import-review-rows">${rows.map(importReviewRowMarkup).join("") || empty("Nenhuma linha na prévia", "Volte e escolha outra origem.")}</div><div class="import-review-actions"><button type="button" class="button" data-import-add-row>+ Adicionar linha à prévia</button><button type="button" class="button ghost" data-import-back>Escolher outra origem</button></div>`, async () => {
      const selected = rows.filter(row => row.include);
      if (!selected.length) throw new Error("Selecione ao menos uma linha para confirmar a importação.");
      if (selected.some(row => row.blocked)) throw new Error("Corrija ou desmarque as linhas com erro antes de confirmar.");
      const emptyName = selected.find(row => !importClean(row.name));
      if (emptyName) throw new Error("Preencha o nome de todas as linhas selecionadas.");
      const keepBoth = selected.find(row => row.duplicate && row.duplicate_action === "keep_both" && existingNames.has(importNameKey(row.name)));
      if (keepBoth) throw new Error("Para manter uma duplicata, renomeie a disciplina antes de confirmar.");
      const items = selected.map(row => ({name:importClean(row.name), code:importClean(row.code) || null, period:importClean(row.period) || null, workload_minutes:row.workload_minutes || null, academic_status:row.academic_status, start_date:importClean(row.start_date) || null, end_date:importClean(row.end_date) || null, notes:importClean(row.notes) || null, sort_order:importSortOrder(row.sort_order), duplicate_action:row.duplicate ? row.duplicate_action : "skip"}));
      const result = await api(`/formations/${formationId}/curriculum/import`, {method:"POST", body:JSON.stringify({confirmed:true, items})});
      window.setTimeout(() => toast(importResultMessage(result)), 0);
    });
    updateImportReviewSummary(form, rows);
    $("[data-import-back]", form).onclick = () => { $("#modal-root").replaceChildren(); openCurriculumImport(formationId, opener); };
    $("[data-import-add-row]", form).onclick = () => {
      rows.push({source_index:"manual", source:"Incluída manualmente na prévia", confidence:null, status_raw:null, requires_review:false, name:"", code:null, period:null, workload_minutes:null, academic_status:"not_available", start_date:null, end_date:null, notes:null, sort_order:rows.length, aliases:[], baseWarnings:[], baseErrors:[], warnings:[], errors:[], serverBlockedWithoutDetails:false, blocked:false, serverDuplicate:false, duplicate:false, duplicate_action:"skip", include:true});
      refreshImportDuplicates(rows, existingNames);
      $("#modal-root").replaceChildren();
      draw();
    };
    form.querySelectorAll("[data-import-drop]").forEach(button => button.onclick = () => {
      rows.splice(Number(button.dataset.importDrop), 1);
      refreshImportDuplicates(rows, existingNames);
      $("#modal-root").replaceChildren();
      draw();
    });
    form.querySelectorAll("[data-import-include]").forEach(input => input.onchange = () => {
      rows[Number(input.dataset.importInclude)].include = input.checked;
      input.closest(".import-review-row")?.classList.toggle("is-excluded", !input.checked);
      updateImportReviewSummary(form, rows);
    });
    form.querySelectorAll("[data-import-field]").forEach(input => {
      const index = Number(input.dataset.importIndex);
      const field = input.dataset.importField;
      input.oninput = () => {
        if (field === "workload_hours") {
          const hours = Number(input.value);
          rows[index].workload_minutes = Number.isFinite(hours) && hours > 0 ? Math.round(hours * 60) : null;
          $(`[data-import-workload="${index}"]`, form).textContent = importWorkloadLabel(rows[index].workload_minutes);
        } else rows[index][field] = input.value;
      };
      input.onchange = () => {
        if (field === "workload_hours") {
          const hours = Number(input.value);
          rows[index].workload_minutes = Number.isFinite(hours) && hours > 0 ? Math.round(hours * 60) : null;
        } else rows[index][field] = input.value;
        clearImportErrorsForField(rows[index], field);
        if (["name", "academic_status", "workload_hours", "sort_order", "start_date", "end_date"].includes(field)) {
          refreshImportDuplicates(rows, existingNames);
          $("#modal-root").replaceChildren();
          draw();
          return;
        }
        updateImportReviewSummary(form, rows);
      };
    });
  };
  refreshImportDuplicates(rows, existingNames);
  draw();
}

function showImportSheetChoice(form, payload) {
  const entries = importSheetEntries(payload?.sheets);
  const holder = $("[data-import-sheet-choice]", form);
  if (!entries.length || !holder) return false;
  holder.hidden = false;
  holder.innerHTML = `<label>Planilha a importar<select name="curriculum_sheet">${entries.map(entry => `<option value="${esc(entry.value)}" ${entry.value === String(payload?.selected_sheet ?? "") ? "selected" : ""}>${esc(entry.label)}</option>`).join("")}</select></label><p class="muted">Escolha uma planilha e gere a prévia novamente. Nada será salvo nesta etapa.</p>`;
  $(".button.primary", form).textContent = "Gerar prévia da planilha";
  return true;
}

function openCurriculumImport(formationId, opener = null) {
  const form = modal("Importar grade curricular", `<p class="muted">Escolha uma origem para criar uma prévia. Nada é salvo antes da confirmação final.</p><div class="import-tabs" role="tablist" aria-label="Forma de importar a grade"><button type="button" class="import-tab active" id="import-tab-file" role="tab" aria-selected="true" aria-controls="import-panel-file" tabindex="0" data-import-tab="file">Arquivo</button><button type="button" class="import-tab" id="import-tab-paste" role="tab" aria-selected="false" aria-controls="import-panel-paste" tabindex="-1" data-import-tab="paste">Colar do Excel/Sheets</button><button type="button" class="import-tab" id="import-tab-guide" role="tab" aria-selected="false" aria-controls="import-panel-guide" tabindex="-1" data-import-tab="guide">Como estruturar</button></div><section class="import-tab-panel" id="import-panel-file" role="tabpanel" aria-labelledby="import-tab-file" data-import-panel="file" tabindex="0"><label>Arquivo da grade<input name="curriculum_file" type="file" accept=".pdf,.docx,.xlsx,.csv,.tsv,.txt" aria-describedby="import-file-help"></label><p class="muted" id="import-file-help">Aceita PDF, DOCX, XLSX, CSV, TSV ou TXT. Se o arquivo tiver várias planilhas, você poderá escolher uma antes da prévia.</p><div data-import-sheet-choice hidden></div></section><section class="import-tab-panel" id="import-panel-paste" role="tabpanel" aria-labelledby="import-tab-paste" data-import-panel="paste" tabindex="0" hidden><label>Cole CSV, TSV ou texto simples<textarea name="curriculum_text" rows="10" placeholder="Disciplina[TAB]Código[TAB]Período[TAB]Carga (h)[TAB]Status[TAB]Ordem[TAB]Data de início[TAB]Data de término[TAB]Observações[TAB]Importar?&#10;Circuitos Elétricos I[TAB]EE101[TAB]1º semestre[TAB]60[TAB]Disponível[TAB]1[TAB]2026-02-01[TAB]2026-06-30[TAB]Turma A[TAB]Sim"></textarea></label><p class="muted">Cole diretamente da planilha. A carga é informada em horas e a prévia mostra a conversão para minutos.</p></section><section class="import-tab-panel" id="import-panel-guide" role="tabpanel" aria-labelledby="import-tab-guide" data-import-panel="guide" tabindex="0" hidden><div class="import-guidance"><strong>Modelo de grade</strong><span>As 10 colunas são: Disciplina, Código, Período, Carga (h), Status, Ordem, Data de início, Data de término, Observações e Importar?.</span><ul class="import-column-guidance"><li><strong>Disciplina</strong> é obrigatória.</li><li><strong>Carga (h)</strong> usa um número positivo em horas.</li><li><strong>Status</strong> deve ser revisado quando não for reconhecido.</li><li><strong>Importar?</strong> aceita Sim ou Não; linhas “Não” ficam fora da confirmação.</li></ul><a class="button ghost" href="/api/curriculum/template">Baixar modelo</a></div></section>`, null);
  const submit = $(".button.primary", form);
  const error = $("[data-form-error]", form);
  const file = $("[name=curriculum_file]", form);
  const text = $("[name=curriculum_text]", form);
  const closeControls = [...form.querySelectorAll("[data-close]")];
  const tabs = [...form.querySelectorAll("[data-import-tab]")];
  const panels = [...form.querySelectorAll("[data-import-panel]")];
  let activeTab = "file";
  let busy = false;
  const updateSubmit = () => {
    const sheetChoice = $("[data-import-sheet-choice]", form);
    submit.textContent = activeTab === "file" && !sheetChoice?.hidden ? "Gerar prévia da planilha" : activeTab === "paste" ? "Gerar prévia do texto" : "Gerar prévia";
    submit.disabled = busy || activeTab === "guide";
  };
  const selectTab = (tab, focus = false) => {
    activeTab = tab;
    tabs.forEach(button => {
      const selected = button.dataset.importTab === tab;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    panels.forEach(panel => { panel.hidden = panel.dataset.importPanel !== tab; });
    updateSubmit();
    if (focus) tabs.find(button => button.dataset.importTab === tab)?.focus();
  };
  tabs.forEach((button, index) => {
    button.onclick = () => selectTab(button.dataset.importTab);
    button.onkeydown = event => {
      let next = null;
      if (event.key === "ArrowRight" || event.key === "ArrowDown") next = (index + 1) % tabs.length;
      if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = (index - 1 + tabs.length) % tabs.length;
      if (event.key === "Home") next = 0;
      if (event.key === "End") next = tabs.length - 1;
      if (next === null) return;
      event.preventDefault();
      selectTab(tabs[next].dataset.importTab, true);
    };
  });
  file.onchange = () => {
    if (!file.files?.[0]) return;
    text.value = "";
    error.textContent = "";
  };
  text.oninput = () => {
    if (!text.value.trim()) return;
    file.value = "";
    const sheetChoice = $("[data-import-sheet-choice]", form);
    if (sheetChoice) { sheetChoice.hidden = true; sheetChoice.replaceChildren(); }
    error.textContent = "";
  };
  const setBusy = value => {
    busy = value;
    updateSubmit();
    closeControls.forEach(button => { button.disabled = value; });
    tabs.forEach(button => { button.disabled = value; });
  };
  updateSubmit();
  form.onsubmit = async event => {
    event.preventDefault();
    if (busy) return;
    error.textContent = "";
    if (activeTab === "guide") return error.textContent = "Escolha Arquivo ou Colar do Excel/Sheets para gerar uma prévia.";
    const selectedFile = activeTab === "file" ? file.files?.[0] : null;
    const pasted = activeTab === "paste" ? text.value.trim() : "";
    const sheet = $("[name=curriculum_sheet]", form)?.value;
    if (file.files?.[0] && text.value.trim()) return error.textContent = "Escolha um arquivo ou o texto colado, não os dois.";
    if (!selectedFile && !pasted) return error.textContent = activeTab === "file" ? "Selecione um arquivo para gerar a prévia." : "Cole a grade para gerar a prévia.";
    setBusy(true);
    try {
      let payload;
      if (selectedFile) {
        const data = new FormData();
        data.append("file", selectedFile);
        if (sheet) data.append("sheet", sheet);
        payload = await api(`/formations/${formationId}/curriculum/preview`, {method:"POST", body:data});
      } else payload = await api(`/formations/${formationId}/curriculum/preview/paste`, {method:"POST", body:JSON.stringify({text:pasted})});
      if (payload?.requires_sheet_selection && !sheet && showImportSheetChoice(form, payload)) {
        setBusy(false);
        error.textContent = "Escolha uma planilha para gerar a prévia.";
        return;
      }
      const existing = await api(`/formations/${formationId}/curriculum?archived=1`);
      const preview = normalizeImportPreview(payload);
      if (!preview.rows.length) throw new Error("Nenhuma disciplina foi identificada. Revise a origem e tente novamente.");
      $("#modal-root").replaceChildren();
      openCurriculumImportReview(formationId, preview, new Set(existing.map(item => importNameKey(item.name))), opener);
    } catch (exception) {
      setBusy(false);
      error.textContent = exception.message || "Não foi possível gerar a prévia.";
    }
  };
}

function studyVisibilityText(study) {
  if (study.visibility_reason_label) return study.visibility_reason_label;
  return studyParentReason(study);
}

function studyActionMarkup(study) {
  const blockedReason = studyVisibilityText(study);
  const archived = Boolean(blockedReason || study.archived_at || study.status === "archived");
  const current = ["active", "paused"].includes(study.status) && !archived;
  const canFocus = study.status === "active" && !archived;
  if (archived) {
    const ownArchive = study.archived_at || study.status === "archived";
    const parentAction = study.formation_archived_at ? '<a class="button primary" href="/formations?filter=archived">Restaurar formação</a>' : study.curriculum_archived_at ? '<a class="button primary" href="/formations">Restaurar disciplina</a>' : "";
    return `<div class="action-unavailable"><span>${esc(blockedReason || "Este estudo está arquivado.")} — restaure o item indicado antes de editar, planejar ou iniciar foco.</span>${ownArchive ? `<button class="button primary" data-study-restore="${study.id}">Restaurar estudo</button>` : parentAction}<button class="button ghost" data-study-dependencies="${study.id}">Dependências</button></div>`;
  }
  return `<details class="action-menu"><summary>Ações</summary><div class="action-menu-content"><button class="button" data-study-detail="${study.id}">Tópicos</button><button class="button" data-edit-study="${study.id}">Editar</button>${study.status === "active" ? `<button class="button" data-study-pause="${study.id}">Pausar</button>` : ""}${study.status === "paused" ? `<button class="button primary" data-study-resume="${study.id}">Continuar</button>` : ""}${canFocus ? `<button class="button primary" data-start-study-focus="${study.id}">Iniciar foco</button>` : ""}${study.origin === "curriculum" && current ? `<button class="button" data-study-finish="${study.id}">Finalizar</button><button class="button" data-study-remove-current="${study.id}">Remover dos atuais</button>` : ""}<button class="button" data-study-archive="${study.id}">Arquivar estudo</button><button class="button ghost" data-study-dependencies="${study.id}">Consultar dependências</button><button class="button danger" data-study-destroy="${study.id}">Excluir definitivamente</button></div></details>`;
}

async function renderStudies() {
  const parameters = new URLSearchParams({visibility:studiesView.visibility, formation_id:studiesView.formationId, q:studiesView.q});
  const [payload, formations] = await Promise.all([api(`/studies?${parameters}`), api("/formations?state=all")]);
  const studies = asRows(payload);
  studiesView.rows = studies;
  syncStudiesLocation();
  const counts = {
    active: studies.filter(study => study.status === "active" && !studyVisibilityText(study)).length,
    paused: studies.filter(study => study.status === "paused" && !studyVisibilityText(study)).length,
    review: studies.filter(study => ["queued", "in_progress"].includes(study.review_status)).length,
    completed: studies.filter(study => study.status === "completed" && !studyVisibilityText(study)).length,
    archived: studies.filter(study => Boolean(studyVisibilityText(study))).length,
  };
  const filters = [["active", "Ativos"], ["paused", "Pausados"], ["review", "Para revisar"], ["completed", "Concluídos"], ["archived", "Arquivados"], ["all", "Todos"]];
  app.innerHTML = `<div class="bar"><div><span class="tag">ESTUDOS ATUAIS</span><p class="muted">${studies.length} estudo(s) nos filtros atuais. Estudos sob formação ou disciplina arquivada aparecem em Arquivados, com o motivo.</p></div><button class="button primary" data-new-study>Novo estudo paralelo</button></div><section class="study-controls" aria-label="Filtros de estudos"><div class="quick-filter-list" role="group" aria-label="Filtro de situação">${filters.map(([value, title]) => `<button class="filter-pill ${studiesView.visibility === value ? "active" : ""}" type="button" data-study-filter="${value}" aria-pressed="${studiesView.visibility === value}">${title}${value !== "all" ? ` <span>${counts[value] || 0}</span>` : ""}</button>`).join("")}</div><label>Formação<select id="study-formation-filter"><option value="">Todas</option>${formations.map(formation => `<option value="${formation.id}" ${String(studiesView.formationId) === String(formation.id) ? "selected" : ""}>${esc(formation.name)}${formation.archived_at ? " · arquivada" : ""}</option>`).join("")}</select></label><label>Pesquisar<input id="study-q" value="${esc(studiesView.q)}" placeholder="Nome da matéria"></label></section><div class="stack">${studies.map(study => { const reason = studyVisibilityText(study); return `<section class="card study-card ${reason ? "is-archived" : ""}"><div class="row"><div><div class="tag-row"><span class="tag">${study.origin === "curriculum" ? "CURRICULAR" : "PARALELO"}</span><span class="status">${label(study.status)}</span>${study.academic_status ? `<span class="status status-${esc(study.academic_status)}">${label(study.academic_status)}</span>` : ""}${study.review_status && study.review_status !== "none" ? `<span class="review-status ${study.review_status}">${curriculumReviewLabel(study.review_status)}</span>` : ""}</div><h2>${esc(study.name)}</h2><p class="muted">${esc(study.formation_name || "Sem formação")} · prioridade ${study.priority}/5 · dificuldade ${study.difficulty}/5 · meta ${study.weekly_goal_minutes ? `${study.weekly_goal_minutes} min/semana` : "não definida"}</p>${reason ? `<p class="archive-reason" role="status">${esc(reason)}. O estudo não pode ser iniciado enquanto o item pai permanecer arquivado.</p>` : ""}</div>${studyActionMarkup(study)}</div><div class="progress"><i style="width:${clampPercent(study.progress_percent)}%"></i></div><p class="muted">Progresso dos tópicos: ${study.completed_topics}/${study.topic_count} (${study.progress_percent}%). Domínio médio: ${study.mastery_average}/5.</p><div id="study-topics-${study.id}"></div></section>`; }).join("") || empty("Nenhum estudo neste filtro", studiesView.visibility === "archived" ? "Não há estudos arquivados ou ocultos por um item pai." : "Adicione uma disciplina da grade ou crie um assunto paralelo.")}</div>`;
  app.querySelectorAll("[data-study-filter]").forEach(button => button.addEventListener("click", () => { studiesView.visibility = button.dataset.studyFilter; syncStudiesLocation(); render(); }));
  $("#study-formation-filter", app)?.addEventListener("change", event => { studiesView.formationId = event.target.value; syncStudiesLocation(); render(); });
  $("#study-q", app)?.addEventListener("input", event => { studiesView.q = event.target.value; window.clearTimeout(studiesView.queryTimer); studiesView.queryTimer = window.setTimeout(() => { syncStudiesLocation(); render(); }, 220); });
}

async function renderReviews() { const reviews = await api("/reviews"); const today = localDateISO(); app.innerHTML = `<div class="grid kpis">${card("Pendentes",reviews.length,"cadeias ativas")}${card("Atrasadas",reviews.filter(item=>item.due_date<today).length,"até hoje")}</div><section class="card"><h2>Revisões</h2>${reviews.map(item => `<div class="list-item row"><div><strong>${esc(item.topic_name)}</strong><div class="muted">${esc(item.subject_name)} · ${item.due_date} · ${item.review_stage === "d1" ? "primeira revisão" : item.review_stage === "d7" ? "segunda revisão" : "revisão de consolidação"}</div></div><div class="review-buttons">${[["wrong","Errei"],["hard","Difícil"],["good","Fui bem"],["easy","Fácil"]].map(([rating,text])=>`<button class="button" data-review="${item.id}" data-rating="${rating}">${text}</button>`).join("")}</div></div>`).join("") || empty("Sem revisões pendentes","Uma sessão relevante cria D+1; depois vêm D+7 e D+30.")}</section>`; }

async function renderHistory() { const rows = await api("/sessions"); app.innerHTML = `<div class="bar"><h2>Histórico real</h2><div><button class="button" data-export>Exportar CSV</button><button class="button primary" data-manual>Registrar sessão</button></div></div><section class="card"><div class="table-wrap"><table class="table"><thead><tr><th>Data</th><th>Matéria / tópico</th><th>Tipo</th><th>Duração</th><th>Horário</th><th></th></tr></thead><tbody>${rows.map(row => `<tr><td>${row.date}</td><td><strong>${esc(row.subject_name)}</strong><div class="muted">${esc(row.topic_name || "Sem tópico")}</div></td><td>${row.entry_method === "review" ? "Revisão" : row.entry_method === "timer" ? "Timer" : "Manual"}</td><td>${hours(row.duration_seconds)}</td><td>${row.started_at && row.ended_at ? `${new Date(row.started_at).toLocaleTimeString("pt-BR",{hour:"2-digit",minute:"2-digit"})}–${new Date(row.ended_at).toLocaleTimeString("pt-BR",{hour:"2-digit",minute:"2-digit"})}` : "—"}</td><td><button class="button ghost" data-delete-session="${row.id}">Excluir</button></td></tr>`).join("")}</tbody></table></div>${!rows.length?empty("Sem sessões","O histórico será preenchido apenas pelo que você realmente estudar."):""}</section>`; }

async function renderAnalytics() {
  const data = await api("/analytics");
  const distribution = Object.fromEntries((data.academic_distribution || []).map(row => [row.status, count(row.count)]));
  const formations = data.academic_progress || [];
  const missingRealSessions = count(data.completed_planned_without_real_session);
  app.innerHTML = `<div class="grid kpis">${card("Tempo real registrado", hours(data.total_seconds), "soma de sessões reais")}${card("Esta semana",hours(data.week_seconds),"sessões reais, segunda a domingo")}${card("Dias estudados",data.days_studied,"datas distintas de sessões reais")}${card("Sessões registradas",data.real_sessions ?? data.sessions,"linhas em sessões de estudo")}${card("Blocos concluídos",data.completed_planned_blocks || 0,"planejamento, não tempo real")}</div>${missingRealSessions ? `<section class="card analytics-warning" role="status"><div><span class="tag warning">REGISTRO PENDENTE</span><h2>${plural(missingRealSessions, "bloco concluído", "blocos concluídos")} sem sessão real</h2><p>Planejamento concluído não é contabilizado automaticamente como tempo estudado. Registre ou corrija a sessão para que a análise reflita o estudo real.</p></div><a class="button primary" href="/history">Registrar sessão real</a></section>` : ""}<section class="grid analytics-layout"><section class="card"><div class="bar"><div><span class="tag">PROGRESSO ACADÊMICO</span><h2>Por formação</h2></div><a class="button ghost" href="/formations">Abrir central de disciplinas</a></div>${formations.map(formation => { const progress = curriculumSummary([], formation.academic_progress || formation, formation); return `<div class="academic-formation-row"><div class="row"><strong>${esc(formation.name)}</strong><span>${progress.percent}%</span></div><div class="progress"><i style="width:${progress.percent}%"></i></div><div class="muted">${progress.completed} concluídas · ${progress.exempted} dispensadas · ${progress.inProgress} em andamento · ${progress.pending} pendentes · ${progress.review} para revisar</div></div>`; }).join("") || empty("Sem formações", "Cadastre uma formação para acompanhar o progresso acadêmico.")}</section><section class="card"><span class="tag">DISTRIBUIÇÃO</span><h2>Situação das disciplinas</h2><div class="status-distribution">${curriculumAcademicStatuses.map(value => `<div><span>${label(value)}</span><strong>${distribution[value] || 0}</strong></div>`).join("")}</div><p class="muted">Concluídas e dispensadas compõem o progresso. “Para revisar” é uma intenção paralela, mostrada dentro de cada formação.</p></section></section><section class="grid analytics-layout"><section class="card"><span class="tag">PRÓXIMAS PENDÊNCIAS</span><h2>Matérias em andamento e pendentes</h2>${(data.next_pending_subjects || []).map(row => `<div class="list-item"><div class="row"><strong>${esc(row.name)}</strong><span class="status status-${esc(row.academic_status)}">${label(row.academic_status)}</span></div><div class="muted">${esc(row.formation_name)} · ${esc(row.period || "Sem período")}${row.review_status && row.review_status !== "none" ? ` · ${curriculumReviewLabel(row.review_status)}` : ""}</div></div>`).join("") || empty("Sem pendências", "Não há disciplinas pendentes nas formações ativas.")}</section><section class="card"><h2>Horas por matéria</h2>${data.by_subject.map(row => `<div class="list-item"><div class="row"><strong>${esc(row.name)}</strong><span>${hours(row.seconds)}</span></div><div class="progress"><i style="width:${data.total_seconds ? Math.round(row.seconds/data.total_seconds*100) : 0}%"></i></div></div>`).join("") || empty("Sem dados", "Registre sessões reais para analisar seus hábitos.")}</section></section>`;
}

async function renderProjects() { const projects = await api("/projects"); app.innerHTML = `<div class="bar"><h2>Projetos</h2><button class="button primary" data-new-project>Novo projeto</button></div><section class="stack">${projects.map(project => `<article class="card"><div class="row"><div><h2>${esc(project.name)}</h2><p class="muted">${esc(project.objective || project.description || "Sem objetivo")}</p></div><button class="button" data-project="${project.id}">Abrir tarefas</button></div><div class="progress"><i style="width:${project.task_count ? project.completed_tasks/project.task_count*100 : 0}%"></i></div><div class="muted">${project.completed_tasks}/${project.task_count} tarefas concluídas</div></article>`).join("") || empty("Nenhum projeto", "Projetos são acompanhados separadamente dos estudos.")}</section>`; }

function newStudy() { modal("Novo estudo paralelo", `<label>Nome<input name="personal_name" required></label><label>Prioridade<input name="priority" type="number" min="1" max="5" value="3"></label><label>Dificuldade<input name="difficulty" type="number" min="1" max="5" value="3"></label><label>Meta semanal (min)<input name="weekly_goal_minutes" type="number" min="1"></label>`, async values => api("/studies",{method:"POST",body:JSON.stringify({...values,priority:Number(values.priority),difficulty:Number(values.difficulty),weekly_goal_minutes:values.weekly_goal_minutes?Number(values.weekly_goal_minutes):null})})); }

function studyEditor(study) { modal(`Editar ${esc(study.name)}`, `<label>Prioridade<input name="priority" type="number" min="1" max="5" value="${study.priority}"></label><label>Dificuldade<input name="difficulty" type="number" min="1" max="5" value="${study.difficulty}"></label><label>Meta semanal (min)<input name="weekly_goal_minutes" type="number" min="1" value="${study.weekly_goal_minutes || ""}"></label><label>Prazo<input name="target_date" type="date" value="${study.target_date || ""}"></label><label>Status<select name="status">${["active","paused"].map(key=>`<option value="${key}" ${key===study.status?"selected":""}>${label(key)}</option>`).join("")}</select></label>`, values => api(`/studies/${study.id}`,{method:"PATCH",body:JSON.stringify({...values,priority:Number(values.priority),difficulty:Number(values.difficulty),weekly_goal_minutes:values.weekly_goal_minutes?Number(values.weekly_goal_minutes):null})})); }

function projectEditor(current = null) { modal(current ? "Editar projeto" : "Novo projeto", `<label>Nome<input name="name" value="${esc(current?.name || "")}" required></label><label>Descrição<textarea name="description">${esc(current?.description || "")}</textarea></label><label>Objetivo<textarea name="objective">${esc(current?.objective || "")}</textarea></label><label>Início<input name="start_date" type="date" value="${current?.start_date || ""}"></label><label>Prazo<input name="target_date" type="date" value="${current?.target_date || ""}"></label><label>Tempo estimado (min)<input name="estimated_minutes" type="number" min="0" value="${current?.estimated_minutes || ""}"></label><label>Status<select name="status">${["active","paused","completed"].map(key=>`<option value="${key}" ${key===current?.status?"selected":""}>${label(key)}</option>`).join("")}</select></label><label>Notas<textarea name="notes">${esc(current?.notes || "")}</textarea></label>`, async values => { values.estimated_minutes=values.estimated_minutes?Number(values.estimated_minutes):null; if (current) await api(`/projects/${current.id}`,{method:"PATCH",body:JSON.stringify(values)}); else await api("/projects",{method:"POST",body:JSON.stringify(values)}); }); }

async function openProject(id) { const project = await api(`/projects/${id}`); const form = modal(esc(project.name), `<p class="muted">${esc(project.objective || project.description || "Sem objetivo")}</p><div class="form-actions"><button type="button" class="button" data-edit-project="${project.id}">Editar</button><button type="button" class="button" data-add-task="${project.id}">+ Tarefa</button></div><section class="topic-panel">${project.tasks.map(task=>`<div class="list-item row"><span>${task.status==="completed"?"✓":"○"} ${esc(task.name)}</span><div><button type="button" class="button ghost" data-toggle-task="${task.id}" data-task-status="${task.status}">${task.status==="completed"?"Reabrir":"Concluir"}</button><button type="button" class="button danger" data-delete-task="${task.id}">Excluir</button></div></div>`).join("") || empty("Sem tarefas","Adicione as etapas do projeto.")}</section>`, null); $(".form-actions .button.primary",form)?.remove(); form.onsubmit = event => event.preventDefault(); }

function openSearch() {
  const form = modal("Buscar no plano", `<label>Buscar formações, disciplinas, estudos e tópicos<input name="query" minlength="2" autofocus required></label><div id="search-results" class="stack"></div>`, async () => {});
  $(".button.primary", form).textContent = "Buscar";
  form.onsubmit = async event => { event.preventDefault(); const query = new FormData(form).get("query"); try { const results = await api(`/search?q=${encodeURIComponent(query)}`); const groups = [["Formações",results.formations,"name"],["Disciplinas",results.curriculum,"name"],["Estudos",results.studies,"name"],["Tópicos",results.topics,"name"]]; $("#search-results",form).innerHTML = groups.map(([title,items,key]) => `<section>${items.length ? `<strong>${title}</strong>${items.map(item=>`<div class="list-item">${esc(item[key])}<div class="muted">${esc(item.formation_name || item.subject_name || item.institution || "")}</div></div>`).join("")}` : ""}</section>`).join("") || empty("Nenhum resultado", "Tente outro termo."); } catch (error) { toast(error.message); } };
}

function openFormationDelete(current, opener) {
  const knownDependencies = formationBlockersText({curriculum_subjects:current.curriculum_count, study_subjects:current.active_studies});
  const dependencyWarning = knownDependencies ? ` Ela ainda possui ${knownDependencies}; apagar dias do planejamento não remove esses vínculos.` : "";
  confirmAction({
    title:"Excluir formação definitivamente",
    message:`Excluir “${current.name}” de forma definitiva? Isso só é permitido quando não há disciplina, estudo ou histórico relacionado.${dependencyWarning} Para tirá-la da lista de ativas preservando seus dados, escolha “Arquivar em vez disso”.`,
    confirmLabel:"Excluir definitivamente",
    fallbackLabel:"Arquivar em vez disso",
    opener,
    onConfirm:async () => {
      await api(`/formations/${current.id}`, {method:"DELETE"});
      formationView.selectedId = null;
      syncFormationLocation();
    },
    onFallback:async () => {
      await api(`/formations/${current.id}/archive`, {method:"POST"});
      formationView.filter = "archived";
      formationView.selectedId = current.id;
      syncFormationLocation();
    },
    formatError:formationDeleteError
  });
}

document.addEventListener("click", async event => { const target = event.target.closest("button, [data-focus]"); if (!target) return; try {
  if (target.dataset.action === "focus") return openPlanningFocus(null, target);
  if (target.dataset.action === "manual-session") return openSession();
  if (target.dataset.action === "search") return openSearch();
  if (target.dataset.focus !== undefined) return openPlanningFocus(null, target);
  if (target.dataset.manual !== undefined) return openSession();
  if (target.dataset.startPlan) return openPlanningFocus(Number(target.dataset.startPlan), target);
  if (target.dataset.availability !== undefined) return openAvailability();
  if (target.dataset.newPlan !== undefined) return openPlanEditor();
  if (target.dataset.plan) return openPlanActions(Number(target.dataset.plan), target);
  if (target.dataset.deletePlanningDay) return openPlanningDayDelete(target.dataset.deletePlanningDay, Number(target.dataset.planningDayCount), target);
  if (target.dataset.generate !== undefined) { const range = planningRange(); return openPlanPreview(await api("/planning/generate",{method:"POST",body:JSON.stringify({start:range.start,days:range.dates.length})})); }
  if (target.dataset.editAvailability) return editAvailability(Number(target.dataset.editAvailability));
  if (target.dataset.deleteAvailability) { await api(`/availability/${target.dataset.deleteAvailability}`,{method:"DELETE"}); toast("Faixa excluída."); return render(); }
  if (target.dataset.newFormation !== undefined) return formationEditor();
  if (target.dataset.editFormation) return formationEditor((await api("/formations?state=all")).find(item => item.id === Number(target.dataset.editFormation)));
  if (target.dataset.formationDependencies) {
    const current = (await api("/formations?state=all")).find(item => item.id === Number(target.dataset.formationDependencies));
    return openDependencies("formations", current.id, current.name, target);
  }
  if (target.dataset.archiveFormation) {
    const current = (await api("/formations?state=all")).find(item => item.id === Number(target.dataset.archiveFormation));
    return openFormationArchive(current, target);
  }
  if (target.dataset.restoreFormation) {
    const current = (await api("/formations?state=all")).find(item => item.id === Number(target.dataset.restoreFormation));
    return openFormationRestore(current, target);
  }
  if (target.dataset.deleteFormation) {
    const current = (await api("/formations?state=all")).find(item => item.id === Number(target.dataset.deleteFormation));
    return openTypedDestroy({kind:"formations", ident:current.id, name:current.name, endpoint:`/formations/${current.id}/destroy`, opener:target, description:"A prévia abaixo inclui disciplinas, estudos e todo o histórico diretamente ligado a esta formação."});
  }
  if (target.dataset.addSubject !== undefined) return curriculumEditor(formationView.selectedId);
  if (target.dataset.editCurriculum) {
    const row = curriculumView.rows?.find(item => item.id === Number(target.dataset.editCurriculum));
    return curriculumEditor(row?.formation_id || formationView.selectedId, row);
  }
  if (target.dataset.curriculumAction) {
    const row = curriculumView.rows?.find(item => item.id === Number(target.dataset.curriculumId));
    if (!row) throw new Error("Não foi possível localizar a disciplina. Atualize a grade e tente novamente.");
    if (target.dataset.curriculumAction === "edit") return curriculumEditor(row.formation_id || formationView.selectedId, row);
    if (target.dataset.curriculumAction === "status") return openCurriculumStatus(row);
    if (target.dataset.curriculumAction === "review") return openCurriculumReview(row);
    if (target.dataset.curriculumAction === "clear-review") return openCurriculumReview(row, "none");
    if (target.dataset.curriculumAction === "archive") { await api(`/curriculum/${row.id}/archive`, {method:"POST"}); toast("Disciplina arquivada."); return render(); }
    if (target.dataset.curriculumAction === "restore") { await api(`/curriculum/${row.id}/restore`, {method:"POST"}); toast("Disciplina restaurada."); return render(); }
    if (target.dataset.curriculumAction === "dependencies") return openDependencies("curriculum", row.id, row.name, target);
    if (target.dataset.curriculumAction === "destroy") return openTypedDestroy({kind:"curriculum", ident:row.id, name:row.name, endpoint:`/curriculum/${row.id}/destroy`, opener:target, description:"A exclusão definitiva pode incluir estudos, tópicos, blocos, sessões, anotações e revisões vinculados a esta disciplina."});
  }
  if (target.dataset.addStudy) { await api(`/curriculum/${target.dataset.addStudy}/add-study`,{method:"POST",body:JSON.stringify({})}); toast("Disciplina adicionada aos estudos."); return render(); }
  if (target.dataset.import !== undefined) return openCurriculumImport(formationView.selectedId, target);
  if (target.dataset.curriculumBulk) return openCurriculumBulkAction(formationView.selectedId, target.dataset.curriculumBulk);
  if (target.dataset.openDuplicateReview) return openDuplicateCandidates(Number(target.dataset.openDuplicateReview));
  if (target.dataset.openDuplicateCandidate !== undefined) {
    const candidate = curriculumView.duplicateCandidates?.[Number(target.dataset.openDuplicateCandidate)];
    return openDuplicateMerge(Number(target.dataset.formationId), candidate);
  }
  if (target.dataset.openStructuralCandidates) return openStructuralCandidates(Number(target.dataset.openStructuralCandidates));
  if (target.dataset.classifyStructural) {
    curriculumView.selectedIds = new Set([Number(target.dataset.classifyStructural)]);
    $("#modal-root").replaceChildren();
    return openCurriculumBulkAction(Number(target.dataset.formationId), "classify");
  }
  if (target.dataset.newStudy !== undefined) return newStudy();
  if (target.dataset.editStudy) {
    const study = studiesView.rows?.find(item => item.id === Number(target.dataset.editStudy)) || (await api("/studies?visibility=all")).find(item => item.id === Number(target.dataset.editStudy));
    return studyEditor(study);
  }
  if (target.dataset.studyPause) { await api(`/studies/${target.dataset.studyPause}/pause`, {method:"POST"}); toast("Estudo pausado."); return render(); }
  if (target.dataset.studyResume) { await api(`/studies/${target.dataset.studyResume}/resume`, {method:"POST"}); toast("Estudo retomado."); return render(); }
  if (target.dataset.studyArchive) { await api(`/studies/${target.dataset.studyArchive}/archive`, {method:"POST"}); toast("Estudo arquivado."); return render(); }
  if (target.dataset.studyRestore) { await api(`/studies/${target.dataset.studyRestore}/restore`, {method:"POST"}); toast("Estudo restaurado."); return render(); }
  if (target.dataset.studyDependencies || target.dataset.studyFinish || target.dataset.studyRemoveCurrent || target.dataset.studyDestroy || target.dataset.startStudyFocus) {
    const studyId = Number(target.dataset.studyDependencies || target.dataset.studyFinish || target.dataset.studyRemoveCurrent || target.dataset.studyDestroy || target.dataset.startStudyFocus);
    const study = studiesView.rows?.find(item => item.id === studyId) || (await api("/studies?visibility=all")).find(item => item.id === studyId);
    if (!study) throw new Error("Não foi possível localizar o estudo. Atualize a lista e tente novamente.");
    if (target.dataset.studyDependencies) return openDependencies("studies", study.id, study.name, target);
    if (target.dataset.studyFinish) return openStudyFinish(study);
    if (target.dataset.studyRemoveCurrent) return openStudyRemoveCurrent(study);
    if (target.dataset.studyDestroy) return openTypedDestroy({kind:"studies", ident:study.id, name:study.name, endpoint:`/studies/${study.id}/destroy`, opener:target, description:"A prévia mostra tópicos, planejamento, sessões, anotações e revisões que dependem deste estudo."});
    if (target.dataset.startStudyFocus) {
      const reason = studyVisibilityText(study);
      if (reason || !["active", "paused"].includes(study.status)) throw new Error(`${reason || "Este estudo não está atual."} Restaure ou retome o estudo antes de iniciar foco.`);
      return startTimer(null, study.id);
    }
  }
  if (target.dataset.newProject !== undefined) return projectEditor();
  if (target.dataset.project) return openProject(Number(target.dataset.project));
  if (target.dataset.editProject) { $("#modal-root").replaceChildren(); return projectEditor(await api(`/projects/${target.dataset.editProject}`)); }
  if (target.dataset.addTask) return modal("Nova tarefa", `<label>Nome<input name="name" required></label>`, values => api(`/projects/${target.dataset.addTask}/tasks`,{method:"POST",body:JSON.stringify(values)}));
  if (target.dataset.toggleTask) { await api(`/project-tasks/${target.dataset.toggleTask}`,{method:"PATCH",body:JSON.stringify({status:target.dataset.taskStatus==="completed"?"pending":"completed"})}); return openProject(Number(target.closest(".modal")?.querySelector("[data-edit-project]")?.dataset.editProject)); }
  if (target.dataset.deleteTask) { await api(`/project-tasks/${target.dataset.deleteTask}`,{method:"DELETE"}); $("#modal-root").replaceChildren(); toast("Tarefa excluída."); return render(); }
  if (target.dataset.studyDetail) { const detail = await api(`/studies/${target.dataset.studyDetail}`); const holder = $(`#study-topics-${detail.id}`); holder.innerHTML = `<div class="topic-panel">${[...detail.groups.flatMap(group => group.topics),...detail.ungrouped_topics].map(topic => `<div class="list-item"><strong>${esc(topic.name)}</strong><div class="muted">${label(topic.status)} · domínio ${topic.mastery}/5</div></div>`).join("") || "<p class='muted'>Sem tópicos.</p>"}<button class="button" data-new-topic="${detail.id}">+ Tópico</button></div>`; return; }
  if (target.dataset.newTopic) return modal("Novo tópico", `<label>Nome<input name="name" required></label><label>Domínio inicial<select name="mastery">${[0,1,2,3,4,5].map(value=>`<option value="${value}">${value}/5</option>`).join("")}</select></label>`, values => api(`/studies/${target.dataset.newTopic}/topics`,{method:"POST",body:JSON.stringify({...values,mastery:Number(values.mastery)})}));
  if (target.dataset.review) { const review = (await api("/reviews")).find(item => item.id === Number(target.dataset.review)); return openSession({review:{...review,rating:target.dataset.rating}}); }
  if (target.dataset.deleteSession) { await api(`/sessions/${target.dataset.deleteSession}`,{method:"DELETE"}); toast("Sessão excluída e domínio reconciliado."); return render(); }
  if (target.dataset.export !== undefined) { const rows = await api("/sessions"); const header = ["data","matéria","tópico","tipo","duração_segundos","início","fim","domínio_antes","domínio_depois","observação"]; const csv = [header,...rows.map(row=>[row.date,row.subject_name,row.topic_name,row.entry_method,row.duration_seconds,row.started_at,row.ended_at,row.mastery_before,row.mastery_after,row.notes])].map(row=>row.map(value=>`"${String(value??"").replaceAll('"','""')}"`).join(",")).join("\n"); const link = document.createElement("a"); link.href=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"})); link.download="historico-plano.csv"; link.click(); URL.revokeObjectURL(link.href); return; }
} catch (error) { toast(error.message); } });

async function render() { try { $("[data-nav='" + page + "']")?.classList.add("active"); $("#date-label").textContent = new Date().toLocaleDateString("pt-BR",{weekday:"long",day:"numeric",month:"long"}); const pages = {today:renderToday,planning:renderPlanning,formations:renderFormations,studies:renderStudies,reviews:renderReviews,history:renderHistory,analytics:renderAnalytics,projects:renderProjects}; await (pages[page] || renderToday)(); } catch (error) { app.innerHTML = empty("Não foi possível carregar esta página", esc(error.message)); } }
render();
