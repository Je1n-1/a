import {api, localDateISO, weekDates} from "./api.js";

const $ = (selector, root = document) => root.querySelector(selector);
const app = $("#app");
const page = document.body.dataset.page;
const weekdays = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"];
const status = {not_available:"Não disponível",available:"Disponível",in_progress:"Em andamento",completed:"Concluída",failed:"Reprovada",locked:"Bloqueada",exempted:"Dispensada",not_started:"Não iniciado",for_review:"Para revisar",planned:"Planejada",skipped:"Não realizada",rescheduled:"Reagendada",cancelled:"Cancelada",active:"Ativo",paused:"Pausado",archived:"Arquivado",queued:"Na fila de revisão",reviewed:"Revisada",withdrawn:"Retirada",scheduled:"Prevista",delivered:"Entregue",corrected:"Corrigida"};
const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[char]));
const hours = value => `${(Number(value || 0) / 3600).toFixed(1).replace(".", ",")} h`;
const empty = (title, message, action = "") => `<div class="empty"><strong>${title}</strong><span>${message}</span>${action}</div>`;
const label = value => status[value] || value || "—";
const toast = message => { $("#toast-root").innerHTML = `<div class="toast">${esc(message)}</div>`; window.setTimeout(() => $("#toast-root").replaceChildren(), 3200); };
const fields = form => Object.fromEntries(new FormData(form));
const weekRange = () => { const dates = weekDates(); return {start: dates[0], end: dates[6], dates}; };
let formationRenderRevision = 0;

function formatLocalDate(value, options = {}) {
  if (!value) return "—";
  const source = /^\d{4}-\d{2}-\d{2}$/.test(String(value)) ? `${value}T12:00:00` : value;
  const date = new Date(source);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("pt-BR", {timeZone:"America/Sao_Paulo", ...options}).format(date);
}

function installResponsiveNavigation() {
  const sidebar = $("#primary-navigation");
  const trigger = $("[data-sidebar-toggle]");
  const main = $("#main-content");
  const skipLink = $(".skip-link");
  if (!sidebar || !trigger) return;
  const media = window.matchMedia("(max-width: 880px)");
  let opener = null;
  const sync = () => {
    const mobile = media.matches;
    const open = document.body.classList.contains("sidebar-open");
    sidebar.toggleAttribute("inert", mobile && !open);
    sidebar.setAttribute("aria-hidden", mobile && !open ? "true" : "false");
    [main, skipLink].filter(Boolean).forEach(element => {
      const backgroundIsInert = mobile && open;
      element.toggleAttribute("inert", backgroundIsInert);
      if (backgroundIsInert) element.setAttribute("aria-hidden", "true"); else element.removeAttribute("aria-hidden");
    });
    trigger.setAttribute("aria-expanded", String(open));
  };
  const close = ({restoreFocus = true} = {}) => {
    if (!document.body.classList.contains("sidebar-open")) return;
    document.body.classList.remove("sidebar-open");
    sync();
    if (restoreFocus) (opener || trigger).focus();
  };
  trigger.addEventListener("click", () => {
    if (document.body.classList.contains("sidebar-open")) return close();
    opener = document.activeElement;
    document.body.classList.add("sidebar-open");
    sync();
    window.setTimeout(() => $("[data-sidebar-close]", sidebar)?.focus(), 0);
  });
  document.querySelectorAll("[data-sidebar-close]").forEach(control => control.addEventListener("click", () => close()));
  sidebar.querySelectorAll("a").forEach(link => link.addEventListener("click", () => close({restoreFocus:false})));
  document.addEventListener("keydown", event => { if (event.key === "Escape") close(); });
  media.addEventListener?.("change", () => { document.body.classList.remove("sidebar-open"); sync(); });
  sync();
}

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
  const tab = params.get("tab") === "ideal" ? "ideal" : "calendar";
  const initial = validCalendarDate(params.get("date")) || calendarDateFromISO(saoPauloTodayISO());
  const proposalStart = validCalendarDate(params.get("plan_start")) || calendarDateFromISO(saoPauloTodayISO());
  const proposalDays = Math.max(1, Math.min(93, Number(params.get("plan_days")) || 7));
  return {mode, tab, cursor: mode === "month" ? calendarMonthStart(initial) : initial, proposalStart, proposalDays};
})();

const analyticsView = (() => {
  const params = new URLSearchParams(window.location.search);
  return {
    range: ["7", "14", "30", "custom"].includes(params.get("range")) ? params.get("range") : "30",
    formationId: params.get("formation_id") || "",
    itemId: params.get("item_id") || "",
    kind: ["", "curriculum", "personal"].includes(params.get("kind")) ? params.get("kind") : "",
    start: params.get("start") || "",
    end: params.get("end") || "",
  };
})();

const reviewsView = {filter:"today"};
const historyView = {range:"30", query:""};
const projectsView = {filter:"active"};

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
  if (planningView.tab === "ideal") url.searchParams.set("tab", "ideal"); else url.searchParams.delete("tab");
  url.searchParams.set("date", calendarISO(planningView.cursor));
  url.searchParams.set("plan_start", calendarISO(planningView.proposalStart));
  url.searchParams.set("plan_days", String(planningView.proposalDays));
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
  const tab = ["overview", "curriculum", "dependencies", "settings"].includes(params.get("tab")) ? params.get("tab") : "overview";
  return {filter, selectedId, tab};
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
  openGroups: new Map(),
};

const studiesView = (() => {
  const params = new URLSearchParams(window.location.search);
  const selectedId = Number(params.get("selected")) || null;
  return {
    visibility: ["active", "paused", "review", "completed", "archived", "all"].includes(params.get("study_filter")) ? params.get("study_filter") : "active",
    formationId: params.get("formation_id") || "",
    q: params.get("study_q") || "",
    selectedId,
    panel: params.get("panel") === "topics" ? "topics" : "",
    expandedStudyId: params.get("panel") === "topics" ? selectedId : null,
    rows: [],
    curriculumRows: [],
    searchRevision: 0,
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
function normalizedText(value) {
  return String(value ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("pt-BR");
}
function minutesLabel(minutes) {
  const value = Math.max(0, Number(minutes) || 0);
  const hoursValue = Math.floor(value / 60);
  const remainder = value % 60;
  if (!hoursValue) return `${remainder} min`;
  return remainder ? `${hoursValue} h ${remainder} min` : `${hoursValue} h`;
}
function parseWeekdays(value) {
  if (Array.isArray(value)) return value.map(Number).filter(day => day >= 0 && day <= 6);
  try { const parsed = JSON.parse(value || "[]"); return Array.isArray(parsed) ? parsed.map(Number).filter(day => day >= 0 && day <= 6) : []; }
  catch { return String(value || "").split(",").map(Number).filter(day => day >= 0 && day <= 6); }
}
function weekdaysInputs(selected = []) {
  const active = new Set(parseWeekdays(selected));
  return `<fieldset class="weekday-picker"><legend>Dias permitidos <span class="field-help">Opcional: sem marcação usa qualquer dia disponível.</span></legend>${weekdays.map((name, index) => `<label><input type="checkbox" name="allowed_weekday" value="${index}" ${active.has(index) ? "checked" : ""}>${name.slice(0, 3)}</label>`).join("")}</fieldset>`;
}
function checkedWeekdays(form) { return [...form.querySelectorAll('[name="allowed_weekday"]:checked')].map(input => Number(input.value)); }
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
  if (formationView.tab !== "overview") url.searchParams.set("tab", formationView.tab);
  else url.searchParams.delete("tab");
  window.history.replaceState({}, "", url);
}

function syncStudiesLocation() {
  if (page !== "studies") return;
  const url = new URL(window.location.href);
  url.searchParams.set("study_filter", studiesView.visibility);
  if (studiesView.formationId) url.searchParams.set("formation_id", studiesView.formationId); else url.searchParams.delete("formation_id");
  if (studiesView.q) url.searchParams.set("study_q", studiesView.q); else url.searchParams.delete("study_q");
  if (studiesView.selectedId) url.searchParams.set("selected", String(studiesView.selectedId)); else url.searchParams.delete("selected");
  if (studiesView.panel === "topics" && studiesView.selectedId) url.searchParams.set("panel", "topics"); else url.searchParams.delete("panel");
  window.history.replaceState({}, "", url);
}

function syncAnalyticsLocation() {
  if (page !== "analytics") return;
  const url = new URL(window.location.href);
  url.searchParams.set("range", analyticsView.range);
  for (const [key, value] of Object.entries({formation_id:analyticsView.formationId, item_id:analyticsView.itemId, kind:analyticsView.kind, start:analyticsView.start, end:analyticsView.end})) {
    if (value) url.searchParams.set(key, value); else url.searchParams.delete(key);
  }
  window.history.replaceState({}, "", url);
}

function modal(title, content, onsubmit) {
  const root = $("#modal-root");
  const returnFocus = document.activeElement;
  const titleId = `modal-title-${Date.now()}`;
  root.innerHTML = `<div class="modal-backdrop" data-modal-backdrop><form class="modal form" role="dialog" aria-modal="true" aria-labelledby="${titleId}" tabindex="-1"><div class="row"><h2 id="${titleId}">${title}</h2><button class="button ghost" type="button" data-close aria-label="Fechar">×</button></div>${content}<p class="form-error" data-form-error role="alert"></p><div class="form-actions"><button class="button" type="button" data-close>Cancelar</button><button class="button primary">Salvar</button></div></form></div>`;
  const backdrop = $("[data-modal-backdrop]", root);
  const form = $(".modal", root);
  const save = $(".button.primary", form);
  const closeControls = [...form.querySelectorAll("[data-close]")];
  let busy = false;
  let closed = false;
  const focusable = () => [...form.querySelectorAll("button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])")].filter(element => element.offsetParent !== null);
  const close = () => {
    if (closed) return;
    closed = true;
    backdrop.removeEventListener("click", onBackdrop);
    document.removeEventListener("keydown", onKey);
    form.dispatchEvent(new Event("modalclose"));
    root.replaceChildren();
    returnFocus?.focus?.();
  };
  const onBackdrop = event => { if (!busy && event.target === backdrop) close(); };
  const onKey = event => {
    if (!root.contains(form)) return document.removeEventListener("keydown", onKey);
    if (event.key === "Escape" && !busy) { event.preventDefault(); return close(); }
    if (event.key !== "Tab") return;
    const items = focusable();
    if (!items.length) return event.preventDefault();
    const first = items[0], last = items.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };
  closeControls.forEach(button => button.addEventListener("click", () => { if (!busy) close(); }));
  form.addEventListener("click", event => { if (!busy && event.target.closest("[data-close]")) close(); });
  backdrop.addEventListener("click", onBackdrop);
  document.addEventListener("keydown", onKey);
  if (onsubmit) form.onsubmit = async event => {
    event.preventDefault();
    if (busy) return;
    const errorMessage = $("[data-form-error]", form);
    busy = true; save.disabled = true; closeControls.forEach(button => { button.disabled = true; }); errorMessage.textContent = "";
    try { await onsubmit(fields(form), form, event); close(); toast(form.dataset.successMessage || "Alteração salva."); render(); }
    catch (error) { busy = false; save.disabled = false; closeControls.forEach(button => { button.disabled = false; }); errorMessage.textContent = error.message || "Não foi possível salvar."; }
  };
  window.setTimeout(() => (focusable()[0] || form).focus(), 0);
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
  const form = modal(`Dependências de ${esc(name)}`, '<section class="dependency-dialog-state" data-dependency-dialog-state role="status" aria-live="polite"><strong>Carregando dependências…</strong><p class="muted">Consultando os vínculos deste item.</p></section>', null);
  const save = $(".button.primary", form);
  save?.remove();
  $(".form-actions", form)?.insertAdjacentHTML("beforeend", '<button class="button primary" type="button" data-close>Entendi</button>');
  $("[data-close]", form)?.focus?.();
  if (opener instanceof HTMLElement) form.dataset.returnFocus = "true";
  const state = $("[data-dependency-dialog-state]", form);
  const load = async () => {
    if (!state) return;
    state.innerHTML = '<strong>Carregando dependências…</strong><p class="muted">Consultando os vínculos deste item.</p>';
    try {
      const dependencies = await api(`/${kind}/${ident}/dependencies`);
      if (!form.isConnected) return;
      state.removeAttribute("role");
      state.innerHTML = `<p class="muted">Esta prévia explica os vínculos que permanecem no histórico ao arquivar e os dados que exigirão confirmação antes de uma exclusão definitiva.</p>${dependencySummaryMarkup(dependencies)}<details class="dependency-raw"><summary>Ver informações detalhadas</summary><pre>${esc(JSON.stringify(dependencies, null, 2))}</pre></details>`;
    } catch (error) {
      if (!form.isConnected) return;
      state.setAttribute("role", "alert");
      state.innerHTML = `<strong>Não foi possível consultar as dependências.</strong><p class="muted">${esc(error.message || "Verifique a conexão e tente novamente.")}</p><button class="button" type="button" data-retry-dependencies>Tentar novamente</button>`;
      $("[data-retry-dependencies]", state)?.addEventListener("click", load);
    }
  };
  load();
  return form;
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
  const needsLink = !row.active_study_id && !curriculumIsArchived(row) && !isStructuralCurriculum(row);
  const form = modal(`Estado acadêmico: ${esc(row.name)}`, `<p class="muted">O estado acadêmico e a intenção de revisão são separados. Concluir a disciplina não elimina uma revisão marcada.</p><label>Estado acadêmico<select name="academic_status">${curriculumAcademicStatuses.map(value => `<option value="${value}" ${value === row.academic_status ? "selected" : ""}>${label(value)}</option>`).join("")}</select></label>${needsLink ? '<section class="curriculum-link-guidance" data-curriculum-link-guidance hidden><strong>Para planejar esta disciplina, ela também precisa entrar em Estudos.</strong><p class="muted">O vínculo cria um estudo atual; depois você poderá incluir tópicos, esforço e meta antes de gerar blocos.</p><label class="toggle-row"><input type="checkbox" name="link_study" value="true" checked> Criar vínculo agora</label></section>' : ""}`, async values => {
    const enteringProgress = values.academic_status === "in_progress" && row.academic_status !== "in_progress";
    if (enteringProgress && needsLink && values.link_study !== "true") throw new Error("Para marcar como em andamento, crie o vínculo em Estudos ou mantenha a disciplina como disponível.");
    await api(`/curriculum/${row.id}/status`, {method:"POST", body:JSON.stringify({academic_status:values.academic_status})});
    if (enteringProgress && needsLink) await api(`/curriculum/${row.id}/add-study`, {method:"POST", body:JSON.stringify({})});
  });
  $(".button.primary", form).textContent = "Atualizar estado";
  const select = $("[name=academic_status]", form);
  const guidance = $("[data-curriculum-link-guidance]", form);
  const syncGuidance = () => { if (guidance) guidance.hidden = select?.value !== "in_progress"; };
  select?.addEventListener("change", syncGuidance);
  syncGuidance();
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
function statCard(title, value, note = "", icon = "•", tone = "violet") {
  return `<article class="card stat-card" data-tone="${esc(tone)}"><span class="stat-card-icon" aria-hidden="true">${icon}</span><div><span class="muted">${esc(title)}</span><div class="metric">${value}</div><div class="muted">${note}</div></div></article>`;
}
function panelTitle(eyebrow, title, description = "", action = "") {
  return `<div class="panel-heading"><div>${eyebrow ? `<span class="tag">${esc(eyebrow)}</span>` : ""}<h2>${esc(title)}</h2>${description ? `<p class="muted">${esc(description)}</p>` : ""}</div>${action}</div>`;
}

async function openSession({planned = null, review = null} = {}) {
  const studies = await api("/studies");
  if (!studies.length) return toast("Crie ou adicione um estudo antes de registrar uma sessão.");
  const preferred = planned?.study_subject_id || review?.study_subject_id || studies[0].id;
  const form = modal(planned ? "Começar sessão planejada" : review ? "Registrar revisão" : "Registrar sessão", `<label>Matéria<select name="study_subject_id" id="session-study">${studyOptions(studies, preferred)}</select></label><label>Tópico<select name="topic_id" id="session-topic"></select></label><label>Data<input name="date" type="date" value="${localDateISO()}" required></label><label>Horário inicial (opcional)<input name="started_at" type="datetime-local"></label><label>Duração (minutos)<input name="minutes" type="number" min="1" value="${planned?.planned_duration_minutes || 25}" required></label><label>Domínio depois<select name="mastery_after"><option value="">Não informar</option>${[0,1,2,3,4,5].map(value => `<option value="${value}">${value}/5</option>`).join("")}</select></label><label><input name="topic_completed" type="checkbox" value="true"> Concluí este tópico</label><label>Se houver blocos automáticos futuros deste tópico<select name="future_blocks_action"><option value="">Perguntar antes de concluir</option><option value="next_topic">Avançar blocos para o próximo tópico</option><option value="replan">Cancelar blocos automáticos e replanejar</option><option value="review">Manter blocos como revisão</option></select></label><p class="field-help">A escolha só é usada se você marcar o tópico como concluído. Blocos manuais nunca são alterados aqui.</p><label>O que foi estudado?<textarea name="notes" placeholder="Dificuldades, exercícios e próximos passos."></textarea></label>`, async values => {
    const seconds = Number(values.minutes) * 60;
    const started = values.started_at ? new Date(values.started_at) : null;
    const ended = started ? new Date(started.getTime() + seconds * 1000) : null;
    const payload = {study_subject_id:Number(values.study_subject_id), topic_id:values.topic_id ? Number(values.topic_id) : null, date:values.date, duration_seconds:seconds, started_at:started?.toISOString(), ended_at:ended?.toISOString(), mastery_after:values.mastery_after === "" ? null : Number(values.mastery_after), topic_completed:values.topic_completed === "true", future_blocks_action:values.future_blocks_action || null, entry_method:review ? "review" : "manual", notes:values.notes};
    if (planned) payload.planned_session_id = planned.id;
    if (review) {
      await api(`/reviews/${review.id}/complete`, {method:"POST", body:JSON.stringify({rating: review.rating, duration_seconds: seconds, notes: values.notes})});
    } else await api("/sessions", {method:"POST", body:JSON.stringify(payload)});
  });
  const study = $("#session-study", form), topic = $("#session-topic", form);
  const load = async () => { topic.innerHTML = topicOptions(await topicsFor(study.value), planned?.topic_id || review?.topic_id); };
  study.onchange = load; await load();
}

async function renderToday() {
  const [data, reviews] = await Promise.all([api("/today"), api("/reviews")]);
  const rec = data.suggestion;
  const agenda = data.agenda || [];
  const dateLabel = formatLocalDate(data.date, {day:"2-digit", month:"2-digit", year:"numeric"});
  const nextAgenda = agenda.find(item => !["completed", "cancelled"].includes(item.status));
  const freeTime = data.on_track ? `<section class="card today-free-time"><span class="tag">FOLGA CONQUISTADA</span><h2>Você está em dia</h2><p>${esc(data.free_time_message || "A demanda obrigatória de hoje já foi cumprida.")}</p>${data.free_time_preference === "preserve" ? `<p class="muted">Sua preferência atual é preservar o tempo livre; nenhuma sugestão foi incluída automaticamente.</p>` : ""}${(data.free_time_options || []).length ? `<div class="tag-row">${data.free_time_options.map(option => `<span class="tag">${esc(option)}</span>`).join("")}</div>` : ""}</section>` : "";
  const suggestion = rec ? `<section class="card today-suggestion">${panelTitle("SUGESTÃO DE ESTUDO", rec.study_subject.name, rec.topic?.name || "Sem conteúdo específico cadastrado", `<div class="action-group"><button type="button" class="button" data-focus-study="${rec.study_subject.id}" data-focus-topic="${rec.topic?.id || ""}">Começar</button><button type="button" class="button primary" data-add-today-suggestion data-suggest-study="${rec.study_subject.id}" data-suggest-topic="${rec.topic?.id || ""}" data-suggest-date="${rec.slot.scheduled_date}" data-suggest-start="${rec.slot.start_time}" data-suggest-duration="${rec.slot.planned_duration_minutes}">Adicionar às ${esc(rec.slot.start_time)}</button></div>`)}<div class="suggestion-reason"><span aria-hidden="true">✦</span><p class="muted">${rec.reasons.map(esc).join(" · ")} · bloco sugerido de ${minutesLabel(rec.slot.planned_duration_minutes)}.</p></div>${rec.alternatives?.length ? `<p class="field-help">Alternativas de menor prioridade: ${esc(rec.alternatives.join(", "))}.</p>` : ""}</section>` : `<section class="card today-suggestion">${data.day_is_full ? empty("Dia já está cheio", "A agenda ocupa a capacidade disponível hoje. Reagende ou altere a disponibilidade se precisar abrir espaço.", '<a href="/planning" class="button ghost">Abrir planejamento</a>') : empty("Sem sugestão adicional", data.suggestion_unavailable ? "Há uma prioridade pendente, mas não cabe um bloco mínimo no horário restante de hoje." : "Cadastre uma meta, esforço necessário ou conteúdo para receber sugestões.", '<a href="/planning" class="button ghost">Abrir planejamento</a>')}</section>`;
  const agendaMarkup = agenda.length ? `<div class="agenda-timeline">${agenda.map(item => {
    const isNext = item.id === nextAgenda?.id;
    const state = label(item.status || "planned");
    const context = planningBlockContext(item);
    return `<article class="agenda-item ${isNext ? "is-next" : ""}"><div class="agenda-time">${esc(item.start_time || "Livre")}</div><div class="agenda-marker" aria-hidden="true"></div><div class="agenda-item-main"><strong>${esc(item.subject_name)}</strong><span>${esc(item.topic_name || "Sessão sem conteúdo")}</span>${context ? `<small class="agenda-item-context">${esc(context)}</small>` : ""}</div><div class="agenda-item-meta"><span class="status">${esc(state)}</span><span>${minutesLabel(item.planned_duration_minutes)}</span></div><button type="button" class="button ${isNext ? "primary" : "ghost"}" data-start-plan="${item.id}">${isNext ? "Começar" : "Abrir"}</button></article>`;
  }).join("")}</div>` : empty("Nenhum bloco agendado", "Use Planejamento para criar blocos ou aproveite a sugestão abaixo.", '<a href="/planning" class="button ghost">Abrir planejamento</a>');
  app.innerHTML = `<section class="today-dashboard"><div class="grid kpis today-kpis">${statCard("Capacidade hoje", minutesLabel(data.capacity_minutes), "janelas disponíveis", "ϟ", "blue")}${statCard("Planejado", minutesLabel(data.planned_minutes), `${agenda.length} bloco(s) na agenda`, "▣", "violet")}${statCard("Estudado", minutesLabel(data.studied_minutes), "sessões reais", "▥", "amber")}${statCard("Livre restante", minutesLabel(data.free_minutes), data.day_is_full ? "dia cheio" : "após os blocos atuais", "◷", "green")}${statCard("Demanda obrigatória hoje", minutesLabel(data.required_minutes), "agenda salva", "◎", "violet")}</div><div class="grid split today-layout"><section class="stack"><section class="card agenda-card">${panelTitle("AGENDA ÚNICA DO DIA", `Agenda de hoje · ${dateLabel}`, "A agenda salva é a prioridade do dia.", '<a href="/planning" class="button ghost">Abrir planejamento</a>')}${agendaMarkup}</section>${freeTime}${suggestion}</section><aside class="stack"><section class="card reviews-today-card">${panelTitle("REVISÕES", "Revisões pendentes", reviews.length ? `${reviews.length} item(ns) aguardando revisão.` : "Nenhuma revisão exige atenção agora.", '<a href="/reviews" class="button ghost">Ver revisões</a>')}${reviews.length ? `<div class="compact-list">${reviews.slice(0, 4).map(item => `<div class="list-item"><strong>${esc(item.topic_name)}</strong><div class="muted">${esc(item.subject_name)} · ${formatLocalDate(item.due_date, {day:"2-digit", month:"2-digit"})}</div></div>`).join("")}</div>` : empty("Sem revisões pendentes", "Uma sessão com conteúdo inicia a sequência D+1, D+7 e D+30.")}</section><section class="card how-to-use-card">${panelTitle("COMO USAR O TEMPO", "Planejar e estudar são coisas diferentes")}<div class="guidance-row"><span aria-hidden="true">☼</span><p>A agenda salva vem primeiro. A sugestão ocupa somente uma faixa livre e não repete uma matéria já agendada hoje.</p></div><div class="guidance-row"><span aria-hidden="true">↗</span><p>O indicador Estudado aumenta somente ao registrar uma sessão real.</p></div></section></aside></div></section>`;
}

async function openAvailability() {
  const checked = weekdays.map((day, index) => `<label><input type="checkbox" name="weekdays" value="${index}" ${index < 5 ? "checked" : ""}><span>${day.slice(0, 3)}</span></label>`).join("");
  const form = modal("Disponibilidade semanal", `<p class="muted">Cadastre uma ou mais faixas. Os intervalos entre elas continuam livres para você.</p><fieldset class="availability-days"><legend>Dias da semana</legend><div>${checked}</div></fieldset><div class="time-range-fields"><label>Início<input name="start_time" type="time" value="06:00" required></label><label>Fim<input name="end_time" type="time" value="11:45" required></label></div><fieldset class="availability-mode"><legend>Como aplicar esta faixa</legend><label><input type="radio" name="mode" value="append"> <span><strong>Adicionar nova faixa</strong><small>Mantém os horários que já existem nesses dias.</small></span></label><label><input type="radio" name="mode" value="replace" checked> <span><strong>Substituir horários dos dias selecionados</strong><small>Remove as faixas atuais somente dos dias marcados.</small></span></label></fieldset><div class="availability-summary" aria-live="polite"><strong data-availability-summary>Seg–Sex · 06:00–11:45</strong><span data-availability-warning>As faixas atuais de Seg–Sex serão substituídas.</span></div>`, async (_, form) => {
    const values = new FormData(form); const days = values.getAll("weekdays").map(Number);
    await api("/availability/batch", {method:"POST", body:JSON.stringify({weekdays:days,start_time:values.get("start_time"),end_time:values.get("end_time"),mode:values.get("mode")})});
  });
  $(".button.primary", form).textContent = "Salvar disponibilidade";
  const summary = $("[data-availability-summary]", form);
  const warning = $("[data-availability-warning]", form);
  const updateSummary = () => {
    const selected = [...form.querySelectorAll('[name="weekdays"]:checked')].map(input => Number(input.value));
    const start = form.elements.start_time.value || "—";
    const end = form.elements.end_time.value || "—";
    const selectedLabels = selected.length === 5 && [0,1,2,3,4].every(day => selected.includes(day)) ? "Seg–Sex" : selected.length ? selected.map(day => weekdays[day].slice(0, 3)).join(", ") : "Nenhum dia";
    summary.textContent = `${selectedLabels} · ${start}–${end}`;
    const replaces = new FormData(form).get("mode") === "replace";
    warning.textContent = replaces ? `As faixas atuais de ${selectedLabels} serão substituídas.` : `A faixa será adicionada sem remover horários existentes.`;
  };
  form.querySelectorAll('input[name="weekdays"], input[name="mode"], input[type="time"]').forEach(input => input.addEventListener("input", updateSummary));
  form.querySelectorAll('input[name="weekdays"], input[name="mode"]').forEach(input => input.addEventListener("change", updateSummary));
}

async function openPlanEditor(id, defaults = {}) {
  const [studies, current] = await Promise.all([api("/studies"), id ? api(`/planned/${id}`) : Promise.resolve(null)]);
  if (!studies.length) return toast("Crie um estudo antes de planejar.");
  const preferredStudyId = current?.study_subject_id || defaults.studyId || studies[0].id;
  const form = modal(current ? "Editar bloco planejado" : "Nova sessão planejada", `<label>Matéria<select name="study_subject_id" id="plan-study">${studyOptions(studies, preferredStudyId)}</select></label><label>Tópico<select name="topic_id" id="plan-topic"></select></label><label>Data<input name="scheduled_date" type="date" value="${current?.scheduled_date || defaults.date || planningDefaultDate()}" required></label><label>Horário<input name="start_time" type="time" value="${current?.start_time || defaults.startTime || ""}"></label><label>Duração (minutos)<input name="planned_duration_minutes" type="number" min="1" value="${current?.planned_duration_minutes || defaults.duration || 50}" required></label>`, async values => {
    const payload = {...values,study_subject_id:Number(values.study_subject_id),topic_id:values.topic_id ? Number(values.topic_id) : null,planned_duration_minutes:Number(values.planned_duration_minutes)};
    if (current) await api(`/planned/${id}`, {method:"PATCH",body:JSON.stringify(payload)}); else await api("/planned", {method:"POST",body:JSON.stringify(payload)});
  });
  const study = $("#plan-study", form), topic = $("#plan-topic", form);
  const load = async () => { topic.innerHTML = topicOptions(await topicsFor(study.value), current?.topic_id || (Number(study.value) === Number(defaults.studyId) ? defaults.topicId : null)); }; study.onchange = load; await load();
}

let focusOpening = false;

function openPlanningFocus(plannedId, opener = null, studyId = null, topicId = null) {
  if (focusOpening) return;
  focusOpening = true;
  if (opener instanceof HTMLButtonElement) opener.disabled = true;
  const url = new URL("/focus", window.location.origin);
  if (plannedId) url.searchParams.set("planned_id", String(plannedId));
  if (studyId) url.searchParams.set("study_id", String(studyId));
  if (topicId) url.searchParams.set("topic_id", String(topicId));
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
  const context = planningBlockContext(current);
  const form = modal("Bloco planejado", `<div class="planning-block-summary"><strong>${esc(current.subject_name)}</strong><span>${esc(current.topic_name || "Sessão sem tópico")}</span><span>${esc(current.scheduled_date)} · ${esc(current.start_time || "Horário livre")} · ${current.planned_duration_minutes} min</span>${context ? `<span class="field-help">${esc(context)}</span>` : ""}</div><p class="muted">Cancelar mantém o bloco no histórico como cancelado. Excluir remove o bloco definitivamente.</p>`, null);
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

function planningInclusiveDays(start, end) {
  const first = validCalendarDate(start);
  const last = validCalendarDate(end);
  if (!first || !last || last < first) return null;
  return Math.round((last - first) / 86400000) + 1;
}

function planningProposalPeriod(start, days) {
  const today = calendarDateFromISO(saoPauloTodayISO());
  const requested = validCalendarDate(start);
  const first = requested && requested >= today ? requested : today;
  const count = Math.max(1, Math.min(93, Number(days) || 7));
  return {start:calendarISO(first), end:calendarISO(calendarAddDays(first, count - 1)), days:count};
}

function planningPreviewSummary(proposal, sessions) {
  const capacity = proposal.capacity || {};
  const warnings = [
    ...(proposal.unscheduled || []).map(item => `${item.name || item.subject_name || "Matéria"}: ${item.reason || "não coube no período"}`),
    ...(proposal.skipped_without_goal || []).map(item => typeof item === "string" ? `${item}: sem esforço ou meta semanal` : `${item.name || "Matéria"}: sem esforço ou meta semanal`),
  ];
  return `<section class="planning-preview-summary"><div><strong>${sessions.length} bloco(s) na prévia</strong><span>${esc(proposal.start || "—")} a ${esc(proposal.end || "—")}</span></div><div><strong>${minutesLabel(capacity.capacity_minutes)}</strong><span>capacidade no período</span></div><div><strong>${minutesLabel(capacity.free_minutes)}</strong><span>livre antes da prévia</span></div><div><strong>${minutesLabel(capacity.demand_minutes)}</strong><span>demanda considerada</span></div></section>${planningDiagnosticMarkup(proposal)}${warnings.length ? `<section class="planning-preview-warning" role="status"><strong>Itens que não entraram por completo</strong><ul>${warnings.map(item => `<li>${esc(item)}</li>`).join("")}</ul></section>` : ""}`;
}

function planningDiagnosticMarkup(proposal) {
  const diagnostics = proposal.diagnostics;
  if (!diagnostics) return "";
  const summary = diagnostics.summary || diagnostics;
  const items = Array.isArray(diagnostics.items) ? diagnostics.items : [];
  const actionableItems = items.filter(item => item.state !== "future");
  const futureItems = items.filter(item => item.state === "future");
  const value = key => Number(summary[key] || 0);
  const itemMarkup = actionableItems.map(item => {
    const reason = item.reasons?.[0] || {};
    const action = reason.action || {};
    const href = String(action.href || "");
    const actionMarkup = href.startsWith("/") ? `<a class="button compact secondary planning-diagnostic-action" href="${esc(href)}">${esc(action.label || "Abrir")}</a>` : "";
    const stateLabel = item.state === "future" ? "Futura" : item.state === "attention" ? "Atenção" : "Ajuste necessário";
    return `<li class="planning-diagnostic-item"><div><span class="planning-diagnostic-state is-${esc(item.state || "ignored")}">${esc(stateLabel)}</span><strong>${esc(item.name || "Item sem nome")}</strong>${item.formation_name ? `<span class="muted">${esc(item.formation_name)}</span>` : ""}<p>${esc(reason.message || "Revise este item antes de gerar o plano.")}</p></div>${actionMarkup}</li>`;
  }).join("");
  const futureNote = futureItems.length ? `<p class="muted planning-diagnostic-future-note">${futureItems.length} disciplina(s) futura(s) permanecem fora da demanda. Consulte-as em Formações quando ficarem disponíveis.</p>` : "";
  const details = itemMarkup ? `<details class="planning-diagnostic-details"><summary>Ver motivos e próximos passos (${actionableItems.length})</summary><ul class="planning-diagnostic-list">${itemMarkup}</ul></details>${futureNote}` : `<p class="muted planning-diagnostic-empty">Todos os itens elegíveis já têm uma leitura clara nesta prévia.</p>${futureNote}`;
  return `<section class="planning-preview-diagnostic" aria-label="Diagnóstico da prévia"><div class="planning-diagnostic-heading"><div><strong>Diagnóstico da prévia</strong><span>O que foi considerado e o que ainda precisa de ação.</span></div></div><div class="planning-diagnostic-summary"><span><b>${value("eligible")}</b> pronto(s)</span><span><b>${value("ignored")}</b> ajuste(s)</span><span><b>${value("future")}</b> futura(s)</span><span><b>${minutesLabel(summary.unallocated_minutes)}</b> não distribuído</span></div>${details}</section>`;
}

function planningPreviewSessionContext(item) {
  const values = [];
  if (item.formation_name) values.push(`Formação: ${item.formation_name}`);
  if (item.deadline_date) values.push(`Prazo: ${formatLocalDate(item.deadline_date, {dateStyle:"short"})}`);
  if (item.risk_label) values.push(item.risk_label);
  if (item.topic_progress_percent !== undefined && item.topic_progress_percent !== null) values.push(`tópico em ${clampPercent(item.topic_progress_percent)}%`);
  if (item.topic_remaining_minutes !== undefined && item.topic_remaining_minutes !== null) values.push(`faltam ${minutesLabel(item.topic_remaining_minutes)}`);
  if (item.remaining_after_minutes !== undefined && item.remaining_after_minutes !== null) values.push(`restam ${minutesLabel(item.remaining_after_minutes)} para alocar`);
  return values.join(" · ");
}

function openPlanPreview(proposal) {
  let sessions = [...(proposal.sessions || [])];
  const form = modal("Prévia do planejamento", `<p class="muted">Nada foi salvo ainda. Revise a distribuição, remova o que não quiser e só então aplique.</p><div data-plan-preview-body></div>`, null);
  const save = $(".button.primary", form);
  save.textContent = "Aplicar plano";
  const renderBody = () => {
    const body = $("[data-plan-preview-body]", form);
    body.innerHTML = `${planningPreviewSummary(proposal, sessions)}<div class="preview-list">${sessions.map((item, index) => `<div class="list-item row"><div><strong>${esc(item.scheduled_date)} · ${esc(item.start_time)} · ${esc(item.subject_name)}</strong><div class="muted">${esc(item.topic_name || "Sessão sem tópico")} · ${minutesLabel(item.planned_duration_minutes)} · origem automática · ${esc(item.reason || "distribuição automática")}</div>${planningPreviewSessionContext(item) ? `<div class="muted preview-session-context">${esc(planningPreviewSessionContext(item))}</div>` : ""}</div><button type="button" class="button danger" data-preview-remove="${index}">Remover</button></div>`).join("") || empty("Nenhum bloco proposto", "Nenhum estudo ativo elegível gerou blocos neste período. Verifique os Estudos atuais, o esforço ou meta semanal e a disponibilidade.")}</div>`;
    body.querySelectorAll("[data-preview-remove]").forEach(button => button.onclick = () => { sessions.splice(Number(button.dataset.previewRemove), 1); renderBody(); });
    save.disabled = sessions.length === 0;
    save.title = sessions.length ? "" : "Não há blocos para aplicar.";
  };
  renderBody();
  form.onsubmit = async event => {
    event.preventDefault();
    if (!sessions.length) return;
    save.disabled = true;
    const error = $("[data-form-error]", form);
    error.textContent = "";
    try {
      await api("/planning/apply", {method:"POST", body:JSON.stringify({sessions})});
      $("[data-close]", form)?.click();
      toast("Plano aplicado. Blocos manuais foram preservados.");
      await render();
    } catch (exception) {
      save.disabled = false;
      error.textContent = exception.message || "Não foi possível aplicar o plano.";
    }
  };
}

function openPlanGenerationDialog() {
  const initial = planningProposalPeriod(calendarISO(planningView.proposalStart), planningView.proposalDays);
  const today = saoPauloTodayISO();
  const upcomingDeadline = validCalendarDate(planningView.nextDeadline) && planningView.nextDeadline >= today ? planningView.nextDeadline : "";
  const form = modal("Gerar prévia do planejamento", `<p class="muted">Escolha o período antes de gerar. A prévia não altera a agenda e a aplicação preserva seus blocos manuais.</p><div class="planning-period-form"><div class="quick-filter-list" role="group" aria-label="Atalhos de período"><button type="button" class="filter-pill" data-plan-period-days="7">Semana · 7 dias</button><button type="button" class="filter-pill" data-plan-period-days="14">2 semanas</button><button type="button" class="filter-pill" data-plan-period-days="30">Mês · 30 dias</button>${upcomingDeadline ? `<button type="button" class="filter-pill" data-plan-period-deadline="${upcomingDeadline}">Até o próximo prazo</button>` : ""}</div><div class="time-range-fields"><label>Início<input name="start" type="date" min="${today}" value="${initial.start}" required></label><label>Fim<input name="end" type="date" min="${today}" value="${initial.end}" required></label></div><p class="field-help" data-planning-period-feedback role="status"></p></div>`, null);
  const save = $(".button.primary", form);
  save.textContent = "Gerar prévia";
  const start = form.elements.start;
  const end = form.elements.end;
  const feedback = $("[data-planning-period-feedback]", form);
  const update = () => {
    const days = planningInclusiveDays(start.value, end.value);
    if (start.value && start.value < today) {
      feedback.textContent = "O início não pode ser anterior a hoje.";
      save.disabled = true;
      return;
    }
    feedback.textContent = days ? `${days} dia(s) no período.` : "Informe um início e fim válidos.";
    save.disabled = !days || days > 93;
    if (days > 93) feedback.textContent = "A prévia aceita no máximo 93 dias.";
  };
  form.querySelectorAll("[data-plan-period-days]").forEach(button => button.onclick = () => {
    const period = planningProposalPeriod(start.value || initial.start, Number(button.dataset.planPeriodDays));
    start.value = period.start;
    end.value = period.end;
    update();
  });
  form.querySelectorAll("[data-plan-period-deadline]").forEach(button => button.onclick = () => {
    const deadline = button.dataset.planPeriodDeadline;
    if (deadline < start.value) start.value = today;
    end.value = deadline;
    update();
  });
  start.oninput = update;
  end.oninput = update;
  update();
  form.onsubmit = async event => {
    event.preventDefault();
    const days = planningInclusiveDays(start.value, end.value);
    if (!days || days > 93 || start.value < today) return update();
    save.disabled = true;
    const error = $("[data-form-error]", form);
    error.textContent = "";
    try {
      planningView.proposalStart = calendarDateFromISO(start.value);
      planningView.proposalDays = days;
      syncPlanningLocation();
      const proposal = await api("/planning/generate", {method:"POST", body:JSON.stringify({start:start.value, days})});
      $("[data-close]", form)?.click();
      openPlanPreview(proposal);
    } catch (exception) {
      save.disabled = false;
      error.textContent = exception.message || "Não foi possível gerar a prévia.";
    }
  };
}

async function editAvailability(id) {
  const current = (await api("/availability")).find(item => item.id === id);
  if (!current) return toast("Esta faixa não foi encontrada.");
  const form = modal(`Editar faixa de ${weekdays[current.weekday]}`, `<p class="muted">${esc(weekdays[current.weekday])} · altere esta faixa sem tocar nas demais.</p><div class="time-range-fields"><label>Início<input name="start_time" type="time" value="${current.start_time}" required></label><label>Fim<input name="end_time" type="time" value="${current.end_time}" required></label></div><label class="toggle-row"><input name="enabled" type="checkbox" value="true" ${current.enabled ? "checked" : ""}> Faixa ativa</label>`, async (values, form) => {
    const data = new FormData(form);
    await api(`/availability/${id}`, {method:"PATCH",body:JSON.stringify({start_time:data.get("start_time"),end_time:data.get("end_time"),enabled:data.get("enabled") === "true"})});
  });
  $(".button.primary", form).textContent = "Salvar faixa";
}

function openPlanningSettings(preferences = {}) {
  const form = modal("Duração, descanso e folga", `<p class="muted">Essas preferências orientam apenas blocos criados automaticamente; sua agenda manual não é apagada nem preenchida sem escolha.</p><div class="settings-grid"><label>Duração padrão (min)<input name="default_session_minutes" type="number" min="1" value="${preferences.default_session_minutes || 50}" required></label><label>Intervalo padrão (min)<input name="planning_break_minutes" type="number" min="0" value="${preferences.planning_break_minutes || 10}" required></label><label>Duração mínima (min)<input name="minimum_session_minutes" type="number" min="1" value="${preferences.minimum_session_minutes || 25}" required></label><label>Duração máxima (min)<input name="maximum_session_minutes" type="number" min="1" value="${preferences.maximum_session_minutes || 120}" required></label><label>Máximo de estudo por dia (min)<input name="daily_max_study_minutes" type="number" min="0" value="${preferences.daily_max_study_minutes || ""}" placeholder="Sem limite"></label><label>Descanso reservado por dia (min)<input name="minimum_rest_minutes" type="number" min="0" value="${preferences.minimum_rest_minutes || ""}" placeholder="Sem reserva"></label></div><label class="toggle-row"><input name="suggest_during_free_time" type="checkbox" value="true" ${String(preferences.suggest_during_free_time ?? "true") !== "false" && String(preferences.suggest_during_free_time ?? "true") !== "0" ? "checked" : ""}> Mostrar sugestões durante a folga</label><label>Quando houver folga<select name="free_time_preference"><option value="suggest" ${(preferences.free_time_preference || "suggest") === "suggest" ? "selected" : ""}>Mostrar opções, sem preencher automaticamente</option><option value="preserve" ${preferences.free_time_preference === "preserve" ? "selected" : ""}>Preservar o horário livre</option></select></label>`, async (values, currentForm) => {
    for (const key of ["default_session_minutes", "minimum_session_minutes", "maximum_session_minutes", "planning_break_minutes", "daily_max_study_minutes", "minimum_rest_minutes"]) values[key] = Number(values[key] || 0);
    values.suggest_during_free_time = currentForm.querySelector("[name=suggest_during_free_time]")?.checked || false;
    if (values.maximum_session_minutes < values.minimum_session_minutes) throw new Error("A duração máxima deve ser maior ou igual à mínima.");
    await api("/settings", {method:"PUT", body:JSON.stringify(values)});
  });
  $(".button.primary", form).textContent = "Salvar preferências";
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

function planningBlockContext(item) {
  const values = [];
  const reason = item?.selection_reason || item?.reason;
  if (reason) values.push(String(reason));
  if (item?.topic_progress_percent !== null && item?.topic_progress_percent !== undefined) values.push(`tópico ${clampPercent(item.topic_progress_percent)}%`);
  if (item?.topic_remaining_minutes !== null && item?.topic_remaining_minutes !== undefined) values.push(`faltam ${minutesLabel(item.topic_remaining_minutes)}`);
  return values.join(" · ");
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

async function renderPlanningLegacy() {
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
  planningView.nextDeadline = (ideal.items || []).map(item => item.deadline || item.deadline_date).filter(value => validCalendarDate(value) && value >= today).sort()[0] || "";
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

function planningRiskMarkup(item) {
  const deadline = item.deadline || "Sem prazo definido";
  const firstDate = item.first_feasible_date ? `<div class="field-help">Primeira conclusão viável: ${esc(item.first_feasible_date)}</div>` : "";
  const reasons = item.urgency_reasons?.length ? ` · ${esc(item.urgency_reasons.join(" · "))}` : "";
  return `<article class="ideal-item risk-${esc(item.risk || "on_track")}"><div class="bar"><div><div class="tag-row"><span class="tag">${item.kind === "personal" ? "PARALELO" : "CURRICULAR"}</span><span class="status">${esc(item.risk_label || "No ritmo")}</span></div><h3>${esc(item.name)}</h3><p class="muted">Prazo: ${esc(deadline)} · ${item.days_remaining === null || item.days_remaining === undefined ? "sem contagem de prazo" : `${item.days_remaining} dia(s) restantes`}</p></div><strong>${minutesLabel(item.remaining_minutes)}</strong></div><div class="ideal-metrics"><span>Real <strong>${minutesLabel(item.real_minutes)}</strong></span><span>Futuro planejado <strong>${minutesLabel(item.future_planned_minutes)}</strong></span><span>Ainda não alocado <strong>${minutesLabel(item.unallocated_minutes)}</strong></span><span>Capacidade até o prazo <strong>${minutesLabel(item.capacity_until_deadline_minutes)}</strong></span><span>Dias disponíveis <strong>${item.available_days_until_deadline}</strong></span><span>Ideal/dia disponível <strong>${item.ideal_minutes_per_available_day == null ? "—" : minutesLabel(item.ideal_minutes_per_available_day)}</strong></span><span>Ideal/semana <strong>${item.ideal_minutes_per_week == null ? "—" : minutesLabel(item.ideal_minutes_per_week)}</strong></span><span>Prioridade efetiva <strong>${item.priority_effective}/10</strong></span></div>${item.deficit_minutes ? `<p class="planning-deficit">Faltam ${minutesLabel(item.remaining_minutes)}, mas há somente ${minutesLabel(item.capacity_until_deadline_minutes)} livres até o prazo. Déficit: ${minutesLabel(item.deficit_minutes)}${item.days_remaining > 0 ? ` · acrescente cerca de ${minutesLabel(Math.ceil(item.deficit_minutes * 7 / Math.max(item.days_remaining, 1)))} por semana ou altere o prazo.` : ""}</p>` : `<p class="field-help">Base ${item.priority_base}/5 + urgência automática ${item.automatic_urgency}/5 = ${item.priority_effective}/10${reasons}</p>`}${firstDate}</article>`;
}

async function renderPlanning() {
  const range = planningRange();
  const today = saoPauloTodayISO();
  const [availability, plannedRows, studies, preferences, ideal] = await Promise.all([
    api("/availability"),
    api(`/planned?start=${encodeURIComponent(range.start)}&end=${encodeURIComponent(range.end)}`),
    api("/studies"),
    api("/settings"),
    api(`/planning/ideal?start=${encodeURIComponent(range.start)}&end=${encodeURIComponent(range.end)}`),
  ]);
  const plannedByDate = plannedRows.reduce((all, item) => {
    const current = all.get(item.scheduled_date) || [];
    current.push(item);
    all.set(item.scheduled_date, current);
    return all;
  }, new Map());
  const periodLabel = planningTitle(range);
  const previousLabel = planningView.mode === "month" ? "Mês anterior" : "Semana anterior";
  const nextLabel = planningView.mode === "month" ? "Próximo mês" : "Próxima semana";
  const monthIndex = planningView.cursor.getUTCMonth();
  const balance = Number(ideal.surplus_minutes || 0);
  const calendarMarkup = `<section class="card planning-calendar-card"><div class="calendar-weekdays" aria-hidden="true">${["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"].map(day => `<span>${day}</span>`).join("")}</div><div class="planning-calendar" role="grid" aria-label="Calendário de ${esc(periodLabel)}">${range.dates.map(date => {
    const day = calendarISO(date);
    const sessions = plannedByDate.get(day) || [];
    const outsideMonth = date.getUTCMonth() !== monthIndex;
    const dayLabel = calendarDayLabel(date);
    const plannedBlockLabel = `${sessions.length} ${sessions.length === 1 ? "bloco planejado" : "blocos planejados"}`;
    const deleteDay = sessions.length ? `<button type="button" class="button ghost danger calendar-day-delete" data-delete-planning-day="${day}" data-planning-day-count="${sessions.length}" aria-label="Excluir os ${plannedBlockLabel} de ${esc(planningDaySummary(day))}" title="Excluir todos os blocos deste dia">Excluir dia</button>` : "";
    return `<article class="calendar-day ${outsideMonth ? "outside-month" : ""} ${day === today ? "today" : ""}" role="gridcell" aria-label="${esc(dayLabel)}${day === today ? ", hoje" : ""}"><header><div class="calendar-day-date"><time datetime="${day}">${date.getUTCDate()}</time><span>${esc(dayLabel.replace(/^\S+\s*/, ""))}</span></div>${deleteDay}</header><div class="calendar-sessions">${sessions.map(item => { const context = planningBlockContext(item); return `<button type="button" class="session session-block" data-plan="${item.id}" aria-label="Abrir ações para ${esc(planningBlockSummary(item))}"><span class="session-time">${esc(item.start_time || "Livre")}</span><strong>${esc(item.subject_name)}</strong><span class="session-topic">${esc(item.topic_name || "Sessão sem conteúdo")}</span><span class="session-duration">${minutesLabel(item.planned_duration_minutes)}</span>${context ? `<span class="session-context">${esc(context)}</span>` : ""}</button>`; }).join("") || `<span class="calendar-free">Dia livre</span>`}</div></article>`;
  }).join("")}</div></section>`;
  const idealMarkup = `<section class="stack ideal-list"><section class="card"><div class="bar"><div><span class="tag">MUNDO IDEAL</span><h2>Esforço e risco por item</h2><p class="muted">O esforço realizado vem somente de sessões reais. Blocos futuros reduzem apenas o que ainda falta alocar.</p></div><button class="button primary" data-generate>Gerar prévia</button></div>${ideal.items?.length ? ideal.items.map(planningRiskMarkup).join("") : empty("Nenhum item planejável", "Ative uma disciplina disponível ou configure um estudo paralelo com esforço ou meta semanal.")}</section><section class="card"><span class="tag">PRÓXIMAS DISCIPLINAS</span><h2>Futuras, fora da demanda atual</h2>${ideal.future_subjects?.length ? ideal.future_subjects.map(item => `<div class="list-item"><strong>${esc(item.name)}</strong><div class="muted">${esc(item.formation_name)} · ${esc(item.start_date || item.end_date || item.deadline_date || "sem data prevista")}</div></div>`).join("") : empty("Nenhuma disciplina futura", "Disciplinas não disponíveis aparecerão aqui, sem ocupar nenhum horário.")}</section></section>`;
  const groupedAvailability = weekdays.map((day, weekday) => ({day, weekday, ranges:availability.filter(item => Number(item.weekday) === weekday)})).filter(group => group.ranges.length);
  const availabilityMarkup = groupedAvailability.length ? `<div class="availability-groups">${groupedAvailability.map(group => `<section class="availability-day-group"><strong>${esc(group.day)}</strong><div class="availability-ranges">${group.ranges.map(item => `<div class="availability-range ${item.enabled === 0 || item.enabled === false ? "is-disabled" : ""}"><span>${esc(item.start_time)}–${esc(item.end_time)}</span><div class="range-actions"><button type="button" class="icon-button" data-edit-availability="${item.id}" aria-label="Editar faixa de ${esc(group.day)} ${esc(item.start_time)} até ${esc(item.end_time)}" title="Editar faixa">✎</button><button type="button" class="icon-button danger" data-delete-availability="${item.id}" aria-label="Excluir faixa de ${esc(group.day)} ${esc(item.start_time)} até ${esc(item.end_time)}" title="Excluir faixa">×</button></div></div>`).join("")}</div></section>`).join("")}</div>` : empty("Nenhuma faixa", "Adicione os horários em que você pode estudar.");
  const sideMarkup = `<aside class="stack planning-side"><section class="card availability-panel">${panelTitle("DISPONIBILIDADE", "Disponibilidade semanal", "Você pode cadastrar mais de uma faixa por dia; os intervalos ficam livres.", '<button type="button" class="button ghost" data-availability>+ Adicionar faixa</button>')}${availabilityMarkup}</section><section class="card planning-preferences">${panelTitle("DURAÇÃO E PAUSA", "Preferências do plano", "Limites e descanso restringem apenas novas sugestões e blocos automáticos.", '<button type="button" class="button ghost" data-edit-planning-settings>Editar preferências</button>')}<dl><div><dt>Bloco padrão</dt><dd>${minutesLabel(preferences.default_session_minutes || 50)}</dd></div><div><dt>Pausa</dt><dd>${minutesLabel(preferences.planning_break_minutes || 10)}</dd></div><div><dt>Limites</dt><dd>${preferences.minimum_session_minutes || 25}–${preferences.maximum_session_minutes || 120} min</dd></div><div><dt>Máximo diário</dt><dd>${preferences.daily_max_study_minutes ? minutesLabel(preferences.daily_max_study_minutes) : "Sem limite"}</dd></div><div><dt>Descanso reservado</dt><dd>${preferences.minimum_rest_minutes ? minutesLabel(preferences.minimum_rest_minutes) : "Não definido"}</dd></div><div><dt>Folga</dt><dd>${preferences.free_time_preference === "preserve" ? "Preservar horário" : "Mostrar opções"}</dd></div></dl></section></aside>`;
  app.innerHTML = `<section class="planning-workspace"><div class="planning-toolbar"><div class="planning-toolbar-group" role="group" aria-label="Área do planejamento"><button type="button" class="button ${planningView.tab === "calendar" ? "primary" : "ghost"}" data-planning-tab="calendar" aria-pressed="${planningView.tab === "calendar"}">Calendário</button><button type="button" class="button ${planningView.tab === "ideal" ? "primary" : "ghost"}" data-planning-tab="ideal" aria-pressed="${planningView.tab === "ideal"}">Mundo ideal</button></div><div class="planning-toolbar-group" role="group" aria-label="Visualização do calendário"><button type="button" class="button ${planningView.mode === "month" ? "primary" : "ghost"}" data-planning-mode="month" aria-pressed="${planningView.mode === "month"}">Mês</button><button type="button" class="button ${planningView.mode === "week" ? "primary" : "ghost"}" data-planning-mode="week" aria-pressed="${planningView.mode === "week"}">Semana</button></div><div class="planning-actions"><button type="button" class="button ghost" data-availability>Disponibilidade</button><button type="button" class="button" data-new-plan>+ Nova sessão</button><button type="button" class="button primary" data-generate>✦ Gerar plano</button></div></div><p class="planning-range-note"><strong>${esc(periodLabel)}</strong><span>Capacidade no intervalo visível: ${formatLocalDate(range.start, {day:"2-digit", month:"2-digit"})} a ${formatLocalDate(range.end, {day:"2-digit", month:"2-digit", year:"numeric"})}. O replanejamento preserva blocos manuais.</span></p><div class="planning-navigation" aria-label="Navegação do calendário"><button type="button" class="button ghost" data-planning-nav="previous">← ${previousLabel}</button><button type="button" class="button" data-planning-nav="today">Hoje</button><button type="button" class="button ghost" data-planning-nav="next">${nextLabel} →</button></div><div class="grid kpis planning-kpis">${statCard("Capacidade", minutesLabel(ideal.capacity_minutes), `livre: ${minutesLabel(ideal.free_minutes)}`, "ϟ", "blue")}${statCard("Planejado", minutesLabel(ideal.planned_minutes), `${plannedRows.length} bloco(s) ativos`, "▣", "violet")}${statCard("Demanda", minutesLabel(ideal.demand_minutes), "ainda não alocada", "▥", "amber")}${statCard(balance >= 0 ? "Folga" : "Déficit", minutesLabel(Math.abs(balance)), balance >= 0 ? "capacidade após a demanda" : "faltam horas na capacidade", balance >= 0 ? "◷" : "!", balance >= 0 ? "green" : "red")}</div><div class="grid split planning-layout">${planningView.tab === "calendar" ? calendarMarkup : idealMarkup}${sideMarkup}</div></section>`;
  syncPlanningLocation();
  app.querySelectorAll("[data-planning-nav]").forEach(button => {
    button.onclick = () => {
      const direction = button.dataset.planningNav;
      if (direction === "today") planningView.cursor = planningView.mode === "month" ? calendarMonthStart(planningToday()) : planningToday();
      else if (planningView.mode === "month") planningView.cursor = calendarAddMonths(planningView.cursor, direction === "previous" ? -1 : 1);
      else planningView.cursor = calendarAddDays(planningView.cursor, direction === "previous" ? -7 : 7);
      syncPlanningLocation(); render();
    };
  });
  app.querySelectorAll("[data-planning-mode]").forEach(button => button.onclick = () => {
    const nextMode = button.dataset.planningMode;
    if (nextMode === planningView.mode) return;
    planningView.mode = nextMode;
    if (nextMode === "month") planningView.cursor = calendarMonthStart(planningView.cursor);
    syncPlanningLocation(); render();
  });
  app.querySelectorAll("[data-planning-tab]").forEach(button => button.onclick = () => {
    planningView.tab = button.dataset.planningTab;
    syncPlanningLocation(); render();
  });
  const goals = document.createElement("section");
  goals.className = "card weekly-goals-panel";
  goals.innerHTML = `${panelTitle("METAS SEMANAIS", "Metas e mínimos garantidos", "A meta semanal se repete no período. Para estudos paralelos, o mínimo é protegido quando há capacidade, sem adiar disciplinas urgentes.")}<p class="field-help">Para planejar uma disciplina em um mês sem criar uma meta recorrente, informe o esforço e o prazo dela em Formações e escolha “Mês · 30 dias” ao gerar a prévia.</p>${studies.length ? studies.map(study => `<form class="goal-form list-item row" data-study="${study.id}"><div><strong>${esc(study.name)}</strong><div class="muted">Meta ${study.weekly_goal_minutes ? `${minutesLabel(study.weekly_goal_minutes)}/semana` : "não definida"}${study.origin === "personal" && study.minimum_weekly_minutes ? ` · mínimo garantido ${minutesLabel(study.minimum_weekly_minutes)}` : ""}</div></div><label class="goal-input">Meta semanal (min)<input name="weekly_goal_minutes" type="number" min="1" value="${study.weekly_goal_minutes || ""}" placeholder="ex.: 180" required></label><button class="button" type="submit">Salvar</button></form>`).join("") : empty("Sem matérias", "Crie ou adicione uma matéria antes de definir a meta.")}`;
  $(".planning-layout > aside", app).append(goals);
  goals.querySelectorAll(".goal-form").forEach(form => form.onsubmit = async event => {
    event.preventDefault();
    const value = Number(new FormData(form).get("weekly_goal_minutes"));
    try { await api(`/studies/${form.dataset.study}`, {method:"PATCH", body:JSON.stringify({weekly_goal_minutes:value})}); toast("Meta semanal atualizada."); render(); }
    catch (error) { toast(error.message); }
  });
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
  const query = normalizedText(curriculumView.q.trim());
  const selected = rows.filter(row => {
    if (curriculumView.quick !== "archived" && curriculumView.visibility === "active" && curriculumIsArchived(row)) return false;
    if (curriculumView.quick !== "archived" && curriculumView.visibility === "archived" && !curriculumIsArchived(row)) return false;
    if (query && !normalizedText(`${row.name || ""} ${row.code || ""}`).includes(query)) return false;
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

async function contentEditor(curriculumId, current = null) {
  const detail = await api(`/curriculum/${curriculumId}/contents`);
  const topics = topicRowsFor(detail);
  const fresh = current ? topics.find(topic => Number(topic.id) === Number(current.id)) || current : null;
  const prerequisites = new Set((fresh?.prerequisite_topic_ids || []).map(Number));
  const candidates = topics.filter(topic => Number(topic.id) !== Number(fresh?.id));
  const form = modal(fresh ? "Editar tópico" : "Adicionar tópico", `<label>Título<input name="name" value="${esc(fresh?.name || "")}" required></label><label>Unidade / módulo<input name="unit" value="${esc(fresh?.unit || "")}" placeholder="Ex.: Módulo 1"></label><label>Descrição<textarea name="description">${esc(fresh?.description || "")}</textarea></label><div class="settings-grid"><label>Tempo estimado (min)<input name="estimated_minutes" type="number" min="1" value="${fresh?.estimated_minutes ?? ""}" placeholder="Divide o esforço total"></label><label>Peso<select name="effort_weight">${topicWeights.map(([value, text]) => `<option value="${value}" ${Number(fresh?.effort_weight || 2) === value ? "selected" : ""}>${text}</option>`).join("")}</select></label><label>Domínio (0–5)<input name="mastery" type="number" min="0" max="5" value="${fresh?.mastery ?? 0}"></label><label>Dificuldade (1–5)<input name="difficulty" type="number" min="1" max="5" value="${fresh?.difficulty ?? ""}"></label><label>Ordem<input name="sort_order" type="number" min="0" value="${fresh?.sort_order ?? topics.length}"></label></div><label>Status<select name="status">${topicStatuses.map(value => `<option value="${value}" ${value === (fresh?.status || "not_started") ? "selected" : ""}>${label(value)}</option>`).join("")}</select></label><label class="toggle-row"><input name="review_requested" type="checkbox" value="true" ${Number(fresh?.review_requested) || fresh?.status === "for_review" ? "checked" : ""}> Indicar este tópico para revisão</label><label>Ao concluir com blocos automáticos futuros<select name="future_blocks_action"><option value="">Perguntar antes de concluir</option><option value="next_topic">Avançar ao próximo tópico</option><option value="replan">Cancelar automáticos e replanejar</option><option value="review">Manter como revisão</option></select></label><label>Observações<textarea name="observations" placeholder="Dúvidas, materiais e próximo passo.">${esc(fresh?.observations || "")}</textarea></label><fieldset class="choice-list"><legend>Pré-requisitos (opcional)</legend>${candidates.length ? candidates.map(topic => `<label><input type="checkbox" name="prerequisite_topic_id" value="${topic.id}" ${prerequisites.has(Number(topic.id)) ? "checked" : ""}> ${esc(topic.name)}<span>${esc(topic.unit || "Sem unidade")} · ${topicDisplayStatus(topic)}</span></label>`).join("") : "<p class=\"muted\">Ainda não há outro tópico desta disciplina.</p>"}</fieldset>`, async (values, editorForm) => {
    const payload = {
      ...values,
      sort_order:Number(values.sort_order || 0),
      mastery:Number(values.mastery || 0),
      difficulty:values.difficulty === "" ? null : Number(values.difficulty),
      estimated_minutes:values.estimated_minutes === "" ? null : Number(values.estimated_minutes),
      effort_weight:Number(values.effort_weight || 2),
      review_requested:editorForm.querySelector("[name=review_requested]")?.checked || false,
      prerequisite_topic_ids:[...editorForm.querySelectorAll("[name=prerequisite_topic_id]:checked")].map(input => Number(input.value)),
    };
    delete payload.prerequisite_topic_id;
    if (fresh) await api(`/contents/${fresh.id}`, {method:"PATCH", body:JSON.stringify(payload)});
    else await api(`/curriculum/${curriculumId}/contents`, {method:"POST", body:JSON.stringify(payload)});
  });
  $(".button.primary", form).textContent = fresh ? "Salvar tópico" : "Adicionar tópico";
  return form;
}

function evaluationEditor(curriculumId, contents, current = null) {
  const selected = new Set((current?.contents || []).map(item => item.id));
  modal(current ? "Editar avaliação" : "Nova avaliação", `<label>Nome<input name="title" value="${esc(current?.title || "")}" required></label><label>Tipo<select name="type">${[["exam","Prova"],["assignment","Trabalho"],["activity","Atividade"],["project","Projeto"],["exercise_list","Lista"],["recovery","Recuperação"],["other","Outro"]].map(([value,text]) => `<option value="${value}" ${value === current?.type ? "selected" : ""}>${text}</option>`).join("")}</select></label><label>Data prevista<input name="date" type="date" value="${esc(current?.date || "")}" required></label><label>Data de entrega<input name="delivery_date" type="date" value="${esc(current?.delivery_date || "")}"></label><label>Peso<input name="weight" type="number" min="0" step="0.01" value="${current?.weight ?? ""}"></label><label>Nota máxima<input name="max_score" type="number" min="0.01" step="0.01" value="${current?.max_score ?? ""}"></label><label>Nota obtida<input name="score" type="number" min="0" step="0.01" value="${current?.score ?? ""}"></label><label>Status<select name="status">${["scheduled","delivered","corrected","cancelled"].map(value => `<option value="${value}" ${value === current?.status ? "selected" : ""}>${label(value)}</option>`).join("")}</select></label><fieldset class="choice-list"><legend>Conteúdos cobrados</legend>${contents.length ? contents.map(content => `<label><input type="checkbox" name="content_id" value="${content.id}" ${selected.has(content.id) ? "checked" : ""}> ${esc(content.name)}${content.unit ? ` · ${esc(content.unit)}` : ""}</label>`).join("") : '<p class="muted">Cadastre conteúdos para relacioná-los à avaliação.</p>'}</fieldset><label>Observações<textarea name="notes">${esc(current?.notes || "")}</textarea></label>`, async (values, form) => {
    ["weight", "max_score", "score"].forEach(key => { values[key] = values[key] === "" ? null : Number(values[key]); });
    values.content_ids = [...form.querySelectorAll('[name="content_id"]:checked')].map(input => Number(input.value));
    delete values.content_id;
    if (current) await api(`/evaluations/${current.id}`, {method:"PATCH", body:JSON.stringify(values)});
    else await api(`/curriculum/${curriculumId}/evaluations`, {method:"POST", body:JSON.stringify(values)});
  });
}

async function openContentHistory(id, opener = null) {
  const data = await api(`/contents/${id}/history`);
  const form = modal(`Histórico · ${esc(data.content.name)}`, `<p class="muted">Tempo real: ${minutesLabel((data.sessions || []).reduce((sum, item) => sum + Math.floor((item.duration_seconds || 0) / 60), 0))} · ${data.sessions.length} sessão(ões)</p><section class="stack">${data.sessions.map(item => `<div class="list-item"><strong>${esc(item.date)}</strong><span>${minutesLabel(Math.floor(item.duration_seconds / 60))}</span></div>`).join("") || empty("Sem sessões", "Este conteúdo ainda não foi estudado.")}</section>`, null);
  $(".button.primary", form)?.remove(); $(".form-actions", form)?.insertAdjacentHTML("beforeend", '<button class="button primary" type="button" data-close>Fechar</button>');
  if (opener) window.setTimeout(() => $("[data-close]", form)?.focus(), 0);
}

async function openCurriculumDetailLegacy(id, opener = null) {
  const data = await api(`/curriculum/${id}`);
  const subject = data.curriculum, effort = data.effort, evaluation = data.evaluations;
  const contentRows = data.contents || [];
  const form = modal(esc(subject.name), `<div class="grid kpis compact-kpis">${card("Acadêmico", label(subject.academic_status), "situação na grade")}${card("Conteúdo", `${data.content_progress.completed}/${data.content_progress.total}`, "conteúdos concluídos")}${card("Esforço real", effort.required_study_minutes ? `${effort.effort_progress_percent || 0}%` : "—", effort.required_study_minutes ? `${minutesLabel(effort.real_minutes)} de ${minutesLabel(effort.required_study_minutes)}` : "defina o esforço pessoal")}</div><section class="card nested-card"><div class="bar"><div><span class="tag">PRAZO E ESFORÇO</span><p class="muted">Início ${esc(subject.start_date || "—")} · término ${esc(subject.end_date || "—")} · prazo ${esc(subject.deadline_date || subject.end_date || "—")}</p><p class="muted">Carga institucional ${formatMinutesAsHours(subject.workload_minutes)} · esforço restante ${effort.remaining_minutes == null ? "—" : minutesLabel(effort.remaining_minutes)} · futuro já planejado ${minutesLabel(effort.future_planned_minutes)}</p></div><button class="button" type="button" data-detail-edit-curriculum="${subject.id}">Editar</button></div></section><section class="card nested-card"><div class="bar"><div><span class="tag">CONTEÚDOS</span><h3>${contentRows.length} conteúdo(s)</h3></div><button class="button" type="button" data-detail-add-content="${subject.id}">+ Conteúdo</button></div>${contentRows.map(item => `<div class="list-item row"><div><strong>${esc(item.name)}</strong><div class="muted">${esc(item.unit || "Sem unidade")} · ${label(item.status)} · estimado ${item.estimated_minutes ? minutesLabel(item.estimated_minutes) : "—"} · real ${minutesLabel(item.real_minutes)}</div></div><span><button class="button ghost" type="button" data-detail-content-history="${item.id}">Histórico</button><button class="button ghost" type="button" data-detail-edit-content="${item.id}">Editar</button></span></div>`).join("") || empty("Sem conteúdos", "Adicione os assuntos que você quer estudar antes mesmo de ativar a disciplina.")}</section><section class="card nested-card"><div class="bar"><div><span class="tag">AVALIAÇÕES E NOTAS</span><h3>${evaluation.evaluations.length} avaliação(ões)</h3><p class="muted">Média simples ${evaluation.simple_average_percent == null ? "—" : `${evaluation.simple_average_percent}%`} · ponderada ${evaluation.weighted_average_percent == null ? "—" : `${evaluation.weighted_average_percent}%`}</p></div><button class="button" type="button" data-detail-add-evaluation="${subject.id}">+ Avaliação</button></div>${evaluation.evaluations.map(item => `<div class="list-item row"><div><strong>${esc(item.title)}</strong><div class="muted">${esc(item.date)} · ${label(item.status)} · ${item.score == null ? "sem nota" : `${item.score}/${item.max_score || "—"}`} ${item.contents?.length ? `· ${item.contents.map(content => esc(content.name)).join(", ")}` : ""}</div></div><button class="button ghost" type="button" data-detail-edit-evaluation="${item.id}">Editar</button></div>`).join("") || empty("Sem avaliações", "Cadastre provas, trabalhos e notas desta disciplina.")}</section><div class="form-actions"><button class="button ghost" type="button" data-detail-timeline="${subject.id}">Linha do tempo</button></div>`, null);
  $(".button.primary", form)?.remove(); $(".form-actions", form)?.insertAdjacentHTML("beforeend", '<button class="button primary" type="button" data-close>Fechar</button>');
  form.dataset.curriculumContents = JSON.stringify(contentRows);
  form.dataset.curriculumId = String(subject.id);
  if (opener) window.setTimeout(() => $("[data-close]", form)?.focus(), 0);
}

async function openCurriculumTimeline(id) {
  const rows = await api(`/curriculum/${id}/timeline`);
  const form = modal("Linha do tempo da disciplina", `<section class="stack">${rows.map(row => `<div class="list-item"><strong>${esc(row.title)}</strong><div class="muted">${esc(row.date)}${row.details ? ` · ${esc(row.details)}` : ""}</div></div>`).join("") || empty("Sem eventos", "Os próximos estudos, conteúdos e avaliações aparecerão aqui.")}</section>`, null);
  $(".button.primary", form)?.remove(); $(".form-actions", form)?.insertAdjacentHTML("beforeend", '<button class="button primary" type="button" data-close>Fechar</button>');
}

async function openCurriculumDetail(id, opener = null) {
  const data = await api(`/curriculum/${id}`);
  const subject = data.curriculum;
  const effort = data.effort;
  const evaluation = data.evaluations;
  const contentRows = data.contents || [];
  const topicSummary = data.topic_effort || data.effort_distribution;
  const topicDetail = {name:subject.name, curriculum_subject_id:subject.id, curriculum:subject, contents:contentRows, topic_effort:topicSummary, effort_distribution:topicSummary};
  const allTopics = topicRowsFor(topicDetail);
  const topicIndexById = new Map(allTopics.map((item, index) => [Number(item.id), index]));
  const byUnit = contentRows.reduce((all, item) => {
    const key = item.unit || "Sem unidade";
    (all.get(key) || all.set(key, []).get(key)).push(item);
    return all;
  }, new Map());
  const contentsMarkup = [...byUnit.entries()].map(([unit, items]) => `<section class="content-unit"><h4>${esc(unit)} <span>${items.length}</span></h4>${items.map(item => {
    const effective = item.effective_estimated_minutes ?? item.estimated_minutes;
    const review = topicReviewText(item);
    const progress = item.effort_progress_percent;
    const index = topicIndexById.get(Number(item.id)) ?? 0;
    const hasPrevious = index > 0;
    const hasNext = index < allTopics.length - 1;
    const progressMarkup = progress === null || progress === undefined ? "" : `<div class="topic-progress-line"><div class="progress" aria-label="${clampPercent(progress)}% do esforço do tópico"><i style="width:${clampPercent(progress)}%"></i></div><span>${clampPercent(progress)}% do esforço</span></div>`;
    return `<div class="list-item row"><div><div class="tag-row"><span class="status">${esc(topicDisplayStatus(item))}</span>${review ? `<span class="review-status queued">${esc(review)}</span>` : ""}</div><strong>${esc(item.name)}</strong><div class="muted">ordem ${index + 1} · peso ${topicWeightLabel(item.effort_weight)} · dificuldade ${item.difficulty || "—"}/5 · estimativa ${effective === null || effective === undefined ? "—" : minutesLabel(effective)} · real ${minutesLabel(item.real_minutes || 0)} · futuro ${minutesLabel(item.future_planned_minutes || 0)} · restante ${item.remaining_minutes === null || item.remaining_minutes === undefined ? "—" : minutesLabel(item.remaining_minutes)} · ${item.session_count || 0} sessão(ões)</div>${progressMarkup}<div class="field-help">${esc(topicPrerequisiteText(item, allTopics))} · última atividade ${esc(topicDate(item.last_activity || item.last_session_date))}${item.started_at ? ` · início ${esc(topicDate(item.started_at))}` : ""}${item.completed_at ? ` · concluído em ${esc(topicDate(item.completed_at))}` : ""}</div>${item.description ? `<div class="field-help">${esc(item.description)}</div>` : ""}${item.observations ? `<div class="field-help"><strong>Observações:</strong> ${esc(item.observations)}</div>` : ""}</div><span class="action-group"><button class="button ghost" type="button" data-curriculum-topic-move="up" data-topic-curriculum="${subject.id}" data-topic-id="${item.id}" ${hasPrevious ? "" : "disabled"} aria-label="Mover ${esc(item.name)} para cima">↑</button><button class="button ghost" type="button" data-curriculum-topic-move="down" data-topic-curriculum="${subject.id}" data-topic-id="${item.id}" ${hasNext ? "" : "disabled"} aria-label="Mover ${esc(item.name)} para baixo">↓</button><button class="button ghost" type="button" data-detail-content-history="${item.id}">Histórico</button><button class="button ghost" type="button" data-detail-edit-content="${item.id}">Editar</button><button class="button ghost" type="button" data-detail-archive-content="${item.id}">Arquivar</button><button class="button danger" type="button" data-detail-delete-content="${item.id}" data-detail-content-name="${esc(item.name)}">Excluir</button></span></div>`;
  }).join("")}</section>`).join("") || empty("Sem conteúdos", "Adicione os assuntos que você quer estudar antes mesmo de ativar a disciplina.");
  const form = modal(esc(subject.name), `<div class="grid kpis compact-kpis">${card("Acadêmico", label(subject.academic_status), "situação na grade")}${card("Conteúdo", `${data.content_progress.completed}/${data.content_progress.total}`, "conteúdos concluídos")}${card("Esforço real", effort.required_study_minutes ? `${effort.effort_progress_percent || 0}%` : "—", effort.required_study_minutes ? `${minutesLabel(effort.real_minutes)} de ${minutesLabel(effort.required_study_minutes)}` : "defina o esforço pessoal")}</div><section class="card nested-card"><div class="bar"><div><span class="tag">PRAZO E ESFORÇO</span><p class="muted">Início ${esc(subject.start_date || "—")} · término ${esc(subject.end_date || "—")} · prazo ${esc(subject.deadline_date || subject.end_date || "—")}</p><p class="muted">Carga institucional ${formatMinutesAsHours(subject.workload_minutes)} · faltam ${effort.remaining_minutes == null ? "—" : minutesLabel(effort.remaining_minutes)} · futuro já planejado ${minutesLabel(effort.future_planned_minutes)} · não alocado ${effort.unallocated_minutes == null ? "—" : minutesLabel(effort.unallocated_minutes)}</p></div><button class="button" type="button" data-detail-edit-curriculum="${subject.id}">Editar</button></div></section><section class="card nested-card"><div class="bar"><div><span class="tag">CONTEÚDOS</span><h3>${contentRows.length} conteúdo(s)</h3><p class="muted">A mesma fonte aparece no planejamento, foco e histórico — não é criada uma cópia ao ativar a disciplina.</p></div><button class="button" type="button" data-detail-add-content="${subject.id}">+ Conteúdo</button></div>${contentsMarkup}</section><section class="card nested-card"><div class="bar"><div><span class="tag">AVALIAÇÕES E NOTAS</span><h3>${evaluation.evaluations.length} avaliação(ões)</h3><p class="muted">Média simples ${evaluation.simple_average_percent == null ? "—" : `${evaluation.simple_average_percent}%`} · ponderada ${evaluation.weighted_average_percent == null ? "—" : `${evaluation.weighted_average_percent}%`}${evaluation.minimum_grade == null ? "" : ` · mínimo ${evaluation.minimum_grade}`}</p></div><button class="button" type="button" data-detail-add-evaluation="${subject.id}">+ Avaliação</button></div>${evaluation.overdue?.length ? `<p class="planning-deficit">${evaluation.overdue.length} avaliação(ões) com prazo vencido.</p>` : ""}${evaluation.evaluations.map(item => `<div class="list-item row"><div><strong>${esc(item.title)}</strong><div class="muted">${esc(item.date)}${item.delivery_date ? ` · entrega ${esc(item.delivery_date)}` : ""} · ${label(item.status)} · ${item.score == null ? "sem nota" : `${item.score}/${item.max_score || "—"}`} ${item.contents?.length ? `· ${item.contents.map(content => esc(content.name)).join(", ")}` : ""}</div></div><span class="action-group"><button class="button ghost" type="button" data-detail-edit-evaluation="${item.id}">Editar</button><button class="button danger" type="button" data-detail-delete-evaluation="${item.id}" data-detail-evaluation-name="${esc(item.title)}">Excluir</button></span></div>`).join("") || empty("Sem avaliações", "Cadastre provas, trabalhos e notas desta disciplina.")}</section><div class="form-actions"><button class="button ghost" type="button" data-detail-timeline="${subject.id}">Linha do tempo</button></div>`, null);
  $(".button.primary", form)?.remove();
  $(".form-actions", form)?.insertAdjacentHTML("beforeend", '<button class="button primary" type="button" data-close>Fechar</button>');
  form.dataset.curriculumContents = JSON.stringify(contentRows);
  form.dataset.curriculumId = String(subject.id);
  form.querySelectorAll(".nested-card")[1]?.querySelector(".bar")?.insertAdjacentHTML("afterend", topicEffortSummaryMarkup(topicSummary, subject.id, "curriculum"));
  if (data.archived_contents?.length) {
    const contentPanel = form.querySelectorAll(".nested-card")[1];
    contentPanel?.insertAdjacentHTML("beforeend", `<details class="archived-content-list"><summary>${data.archived_contents.length} conteúdo(s) arquivado(s)</summary>${data.archived_contents.map(item => `<div class="list-item row"><span>${esc(item.name)}</span><button type="button" class="button ghost" data-detail-restore-content="${item.id}">Restaurar</button></div>`).join("")}</details>`);
  }
  if (opener) window.setTimeout(() => $("[data-close]", form)?.focus(), 0);
}

function curriculumActionsMarkup(row, formation = {}) {
  const formationArchived = Boolean(formation?.archived_at);
  if (formationArchived) return `<div class="action-unavailable"><span>Restaure a formação para alterar esta disciplina.</span><button class="button ghost" data-restore-formation="${formation.id}">Restaurar formação</button></div>`;
  const review = row.review_status || "none";
  const reviewAction = review === "none" ? "Marcar para revisar" : review === "reviewed" ? "Reabrir revisão" : "Editar revisão";
  const canAddStudy = !row.active_study_id && ["available", "in_progress"].includes(row.academic_status) && !curriculumIsArchived(row) && !isStructuralCurriculum(row);
  const missingStudyLink = row.academic_status === "in_progress" && !row.active_study_id && !curriculumIsArchived(row) && !isStructuralCurriculum(row);
  const addStudyReason = isStructuralCurriculum(row) ? "Linha estrutural não pode entrar nos estudos atuais." : curriculumIsArchived(row) ? "Restaure a disciplina antes de adicionar aos estudos." : "A disciplina precisa estar disponível ou em andamento para entrar nos estudos atuais.";
  return `<details class="action-menu"><summary>Ações</summary><div class="action-menu-content">${missingStudyLink ? '<p class="action-explanation"><strong>Em andamento, mas sem estudo atual.</strong> Vincule-a para incluir tópicos, meta e planejamento.</p>' : ""}<button class="button" data-curriculum-action="details" data-curriculum-id="${row.id}">Conteúdos e avaliações</button><button class="button" data-curriculum-action="edit" data-curriculum-id="${row.id}">Editar</button><button class="button" data-curriculum-action="status" data-curriculum-id="${row.id}">Alterar estado acadêmico</button><button class="button" data-curriculum-action="review" data-curriculum-id="${row.id}">${reviewAction}</button>${review !== "none" ? `<button class="button ghost" data-curriculum-action="clear-review" data-curriculum-id="${row.id}">Retirar da revisão</button>` : ""}${row.active_study_id ? `<a class="button" href="/studies?study_filter=all&selected=${row.active_study_id}&panel=topics">Abrir tópicos do estudo</a><button class="button" data-study-remove-current="${row.active_study_id}">Encerrar estudo vinculado</button>` : canAddStudy ? `<button class="button" data-add-study="${row.id}" data-add-study-formation="${formation.id}">${missingStudyLink ? "Vincular aos estudos atuais" : "Iniciar estudo"}</button>` : `<p class="action-explanation">${esc(addStudyReason)}</p>`}${curriculumIsArchived(row) ? `<button class="button primary" data-curriculum-action="restore" data-curriculum-id="${row.id}">Restaurar disciplina</button>` : `<button class="button" data-curriculum-action="archive" data-curriculum-id="${row.id}">Arquivar disciplina</button>`}<button class="button ghost" data-curriculum-action="dependencies" data-curriculum-id="${row.id}">Consultar dependências</button><button class="button danger" data-curriculum-action="destroy" data-curriculum-id="${row.id}">Excluir definitivamente</button></div></details>`;
}

function curriculumTableMarkup(key, title, rows, formation) {
  const groupId = `curriculum-group-${key}`;
  const panelId = `${groupId}-panel`;
  const queryActive = Boolean(curriculumView.q.trim() || curriculumView.academicStatus);
  const open = queryActive ? rows.length > 0 : curriculumView.openGroups.has(key) ? curriculumView.openGroups.get(key) : ["in_progress", "available"].includes(key);
  const rowMarkup = rows.map(row => {
    const dates = `${row.start_date || "—"} → ${row.end_date || "—"}${row.deadline_date ? `<br><span class="muted">prazo ${esc(row.deadline_date)}</span>` : ""}`;
    const effort = row.required_study_minutes ? `${formatMinutesAsHours(row.required_study_minutes)}<br><span class="muted">base ${row.priority_base || 3}/5</span>` : '<span class="muted">não definido</span>';
    const linkedStudy = row.active_study_id ? '<span class="field-help">Estudo atual vinculado</span>' : row.academic_status === "in_progress" ? '<span class="curriculum-link-missing">Sem estudo atual vinculado</span>' : "";
    return `<tr class="${curriculumIsArchived(row) ? "is-archived" : ""} ${isStructuralCurriculum(row) ? "is-structural" : ""}"><td><input type="checkbox" data-curriculum-select="${row.id}" ${curriculumView.selectedIds.has(row.id) ? "checked" : ""} aria-label="Selecionar ${esc(row.name)}"></td><td><strong>${esc(row.name)}</strong><div class="muted">${isStructuralCurriculum(row) ? "Linha estrutural · " : ""}${esc(row.code || "Sem código")} · ${formatMinutesAsHours(row.workload_minutes)} · ordem ${row.sort_order ?? 0}</div></td><td>${esc(row.period || "—")}</td><td class="muted">${dates}</td><td>${effort}</td><td><span class="status status-${esc(row.academic_status)}">${label(row.academic_status)}</span>${linkedStudy}</td><td><span class="review-status ${row.review_status || "none"}">${curriculumReviewLabel(row.review_status)}</span>${row.review_priority ? `<div class="muted">prioridade ${row.review_priority}/5</div>` : ""}</td><td class="muted">${esc(row.updated_at || row.created_at || "—")}</td><td>${curriculumActionsMarkup(row, formation)}</td></tr>`;
  }).join("");
  return `<details class="curriculum-section curriculum-status-group" data-curriculum-group="${key}" ${open ? "open" : ""}><summary id="${groupId}" aria-controls="${panelId}" aria-expanded="${open}"><span>${esc(title)}</span><span class="status-count" aria-label="${rows.length} disciplinas">${rows.length}</span></summary><div id="${panelId}" class="curriculum-table-region" data-curriculum-table-region><div class="curriculum-table-scroll-top" aria-hidden="true"><div></div></div><div class="table-wrap curriculum-table-wrap" data-curriculum-table-wrap tabindex="0" role="region" aria-labelledby="${groupId}"><table class="table curriculum-table"><caption class="sr-only">${esc(title)} da grade curricular</caption><thead><tr><th><label class="select-all-label"><input class="curriculum-select-all" type="checkbox" ${rows.length && rows.every(row => curriculumView.selectedIds.has(row.id)) ? "checked" : ""} aria-label="Selecionar todas as disciplinas visíveis em ${esc(title)}"> Selecionar</label></th><th>Disciplina</th><th>Período</th><th>Datas / prazo</th><th>Esforço</th><th>Estado acadêmico</th><th>Revisão</th><th>Atualização</th><th>Ações</th></tr></thead><tbody>${rowMarkup}</tbody></table></div></div></details>`;
}

function curriculumSectionsMarkup(rows, formation = {}) {
  const groups = [
    ["in_progress", "Em andamento", row => !curriculumIsArchived(row) && !isStructuralCurriculum(row) && row.academic_status === "in_progress"],
    ["available", "Disponíveis", row => !curriculumIsArchived(row) && !isStructuralCurriculum(row) && row.academic_status === "available"],
    ["not_available", "Futuras / não disponíveis", row => !curriculumIsArchived(row) && !isStructuralCurriculum(row) && row.academic_status === "not_available"],
    ["locked", "Bloqueadas", row => !curriculumIsArchived(row) && !isStructuralCurriculum(row) && row.academic_status === "locked"],
    ["completed", "Concluídas", row => !curriculumIsArchived(row) && !isStructuralCurriculum(row) && row.academic_status === "completed"],
    ["failed", "Reprovadas", row => !curriculumIsArchived(row) && !isStructuralCurriculum(row) && row.academic_status === "failed"],
    ["exempted", "Dispensadas", row => !curriculumIsArchived(row) && !isStructuralCurriculum(row) && row.academic_status === "exempted"],
    ["structural", "Linhas estruturais", row => !curriculumIsArchived(row) && isStructuralCurriculum(row)],
    ["archived", "Arquivadas", row => curriculumIsArchived(row)],
  ];
  const visibleGroups = groups.map(([key, title, predicate]) => [key, title, rows.filter(predicate)]).filter(([key, , items]) => items.length && (key !== "archived" || curriculumView.visibility !== "active"));
  if (!visibleGroups.length) return empty("Nenhuma disciplina encontrada", curriculumView.q.trim() ? `Não há resultados para “${curriculumView.q.trim()}”.` : "Ajuste os filtros ou cadastre uma nova disciplina.", '<button class="button ghost" type="button" data-clear-curriculum-filters>Limpar filtros</button>');
  return `<section class="curriculum-sections" aria-label="Grade curricular por estado acadêmico">${visibleGroups.map(([key, title, items]) => curriculumTableMarkup(key, title, items, formation)).join("")}</section>`;
}

function syncCurriculumTableScrollers(root = app) {
  root.querySelectorAll("[data-curriculum-table-region]").forEach(region => {
    const top = $(".curriculum-table-scroll-top", region);
    const bottom = $("[data-curriculum-table-wrap]", region);
    const spacer = top?.firstElementChild;
    if (!top || !bottom || !spacer) return;
    const syncSize = () => { spacer.style.width = `${bottom.scrollWidth}px`; top.hidden = bottom.scrollWidth <= bottom.clientWidth + 1; };
    let syncing = false;
    top.addEventListener("scroll", () => { if (syncing) return; syncing = true; bottom.scrollLeft = top.scrollLeft; syncing = false; });
    bottom.addEventListener("scroll", () => { if (syncing) return; syncing = true; top.scrollLeft = bottom.scrollLeft; syncing = false; });
    syncSize();
    window.addEventListener("resize", syncSize, {once:true});
  });
}

function renderCurriculumResults(formation, allRows) {
  const root = $("#curriculum-results", app);
  const rows = curriculumLocalFilter(allRows);
  if (!root) return rows;
  root.innerHTML = `<p class="curriculum-result-count" aria-live="polite">${rows.length} resultado(s) de ${allRows.length}. A revisão continua visível dentro de cada disciplina; ela não altera o estado acadêmico.</p>${curriculumQuickFilters()}<div class="curriculum-result-actions"><button type="button" class="button ghost" data-clear-curriculum-filters>Limpar filtros</button></div>${curriculumBulkToolbar(formation.id, rows)}${curriculumSectionsMarkup(rows, formation)}`;
  root.querySelectorAll("[data-curriculum-quick]").forEach(button => button.addEventListener("click", () => {
    const nextQuick = button.dataset.curriculumQuick;
    if (nextQuick === "archived" && curriculumView.visibility !== "archived") { curriculumView.quick = nextQuick; curriculumView.visibility = "archived"; return render(); }
    if (curriculumView.quick === "archived" && curriculumView.visibility === "archived") curriculumView.visibility = "active";
    curriculumView.quick = nextQuick;
    renderCurriculumResults(formation, allRows);
  }));
  root.querySelectorAll("[data-clear-curriculum-filters]").forEach(button => button.addEventListener("click", () => {
    curriculumView.q = ""; curriculumView.period = ""; curriculumView.academicStatus = ""; curriculumView.reviewStatus = ""; curriculumView.quick = "all"; curriculumView.sort = "period";
    [["#curriculum-q", ""], ["#curriculum-period", ""], ["#curriculum-status", ""], ["#curriculum-review", ""], ["#curriculum-sort", "period"]].forEach(([selector, value]) => { const control = $(selector, app); if (control) control.value = value; });
    renderCurriculumResults(formation, allRows);
    $("#curriculum-q", app)?.focus();
  }));
  root.querySelectorAll(".curriculum-select-all").forEach(input => input.addEventListener("change", event => {
    const section = event.target.closest(".curriculum-status-group");
    const ids = [...section.querySelectorAll("[data-curriculum-select]")].map(control => Number(control.dataset.curriculumSelect));
    ids.forEach(id => event.target.checked ? curriculumView.selectedIds.add(id) : curriculumView.selectedIds.delete(id));
    renderCurriculumResults(formation, allRows);
  }));
  root.querySelectorAll("[data-curriculum-select]").forEach(input => input.addEventListener("change", event => {
    const id = Number(event.target.dataset.curriculumSelect);
    event.target.checked ? curriculumView.selectedIds.add(id) : curriculumView.selectedIds.delete(id);
    renderCurriculumResults(formation, allRows);
  }));
  root.querySelectorAll("[data-curriculum-group]").forEach(group => group.addEventListener("toggle", () => {
    curriculumView.openGroups.set(group.dataset.curriculumGroup, group.open);
    group.querySelector("summary")?.setAttribute("aria-expanded", String(group.open));
  }));
  syncCurriculumTableScrollers(root);
  return rows;
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
  let drawRevision = 0;
  const formations = await api(`/formations?state=${formationView.filter}`);
  let selected = formations.find(item => item.id === formationView.selectedId) || formations[0] || null;
  formationView.selectedId = selected?.id || null;
  if (curriculumView.formationId !== selected?.id) {
    curriculumView.formationId = selected?.id || null;
    curriculumView.selectedIds.clear();
    curriculumView.openGroups.clear();
  }
  syncFormationLocation();

  const draw = async () => {
    const currentDraw = ++drawRevision;
    const requestedSelection = selected;
    const parameters = new URLSearchParams({visibility:curriculumView.visibility});
    const management = requestedSelection ? await api(`/formations/${requestedSelection.id}/curriculum/management?${parameters}`) : {items:[], summary:{}, periods:[]};
    if (currentDraw !== drawRevision || renderRevision !== formationRenderRevision || requestedSelection?.id !== selected?.id) return;
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
    const curriculumTable = null;
    if (curriculumTable && rows.length) {
      const header = $("thead tr", curriculumTable);
      const periodHeader = header?.children[2];
      if (periodHeader) {
        periodHeader.insertAdjacentHTML("afterend", "<th>Datas / prazo</th><th>Esforço</th>");
      }
      [...curriculumTable.querySelectorAll("tbody tr")].slice(0, rows.length).forEach((tr, index) => {
        const row = rows[index];
        const periodCell = tr.children[2];
        if (!periodCell) return;
        const dates = `${row.start_date || "—"} → ${row.end_date || "—"}${row.deadline_date ? `<br><span class=\"muted\">prazo ${esc(row.deadline_date)}</span>` : ""}`;
        const effort = row.required_study_minutes ? `${formatMinutesAsHours(row.required_study_minutes)}<br><span class=\"muted\">base ${row.priority_base || 3}/5</span>` : "<span class=\"muted\">não definido</span>";
        periodCell.insertAdjacentHTML("afterend", `<td class="muted">${dates}</td><td>${effort}</td>`);
      });
    }
    $(".formation-delete-hint", app)?.remove();
    const curriculumManagement = $(".curriculum-management", app);
    if (curriculumManagement && selected) {
      curriculumManagement.innerHTML = `<div class="bar"><div><span class="tag">CENTRAL DE DISCIPLINAS</span><h2>Grade curricular</h2><p class="muted">Organize a grade por estado acadêmico. Revisão aparece dentro da disciplina e não cria uma categoria acadêmica paralela.</p></div>${curriculumActions}</div><section class="curriculum-controls" aria-label="Filtros da grade"><label>Pesquisar<input id="curriculum-q" value="${esc(curriculumView.q)}" placeholder="Nome ou código" autocomplete="off"></label><label>Período / módulo<select id="curriculum-period"><option value="">Todos</option>${periods.map(value => `<option value="${esc(value)}" ${curriculumView.period === value ? "selected" : ""}>${esc(value)}</option>`).join("")}</select></label><label>Estado acadêmico<select id="curriculum-status"><option value="">Todos</option>${curriculumAcademicStatuses.map(value => `<option value="${value}" ${curriculumView.academicStatus === value ? "selected" : ""}>${label(value)}</option>`).join("")}</select></label><label>Revisão<select id="curriculum-review"><option value="">Todas</option>${curriculumReviewStatuses.map(value => `<option value="${value}" ${curriculumView.reviewStatus === value ? "selected" : ""}>${curriculumReviewLabel(value)}</option>`).join("")}</select></label><label>Visibilidade<select id="curriculum-visibility"><option value="active" ${curriculumView.visibility === "active" ? "selected" : ""}>Ativas</option><option value="archived" ${curriculumView.visibility === "archived" ? "selected" : ""}>Arquivadas</option><option value="all" ${curriculumView.visibility === "all" ? "selected" : ""}>Todas</option></select></label><label>Ordenar<select id="curriculum-sort"><option value="period" ${curriculumView.sort === "period" ? "selected" : ""}>Período</option><option value="order" ${curriculumView.sort === "order" ? "selected" : ""}>Ordem</option><option value="name" ${curriculumView.sort === "name" ? "selected" : ""}>Nome</option><option value="status" ${curriculumView.sort === "status" ? "selected" : ""}>Status</option><option value="updated" ${curriculumView.sort === "updated" ? "selected" : ""}>Atualização</option></select></label></section><div id="curriculum-results"></div>`;
      renderCurriculumResults(selected, allRows);
    }
    const detailStack = $(".formation-layout > section.stack", app);
    const overviewPanel = detailStack?.querySelector(":scope > section.card:not(.curriculum-management)");
    const curriculumPanel = detailStack?.querySelector(":scope > .curriculum-management");
    if (detailStack && overviewPanel && curriculumPanel && selected) {
      overviewPanel.classList.add("formation-tab-panel");
      overviewPanel.dataset.formationPanel = "overview";
      overviewPanel.id = `formation-overview-${selected.id}`;
      overviewPanel.setAttribute("role", "tabpanel");
      overviewPanel.setAttribute("aria-labelledby", `formation-tab-overview-${selected.id}`);
      curriculumPanel.classList.add("formation-tab-panel");
      curriculumPanel.dataset.formationPanel = "curriculum";
      curriculumPanel.id = `formation-curriculum-${selected.id}`;
      curriculumPanel.setAttribute("role", "tabpanel");
      curriculumPanel.setAttribute("aria-labelledby", `formation-tab-curriculum-${selected.id}`);

      const dependenciesPanel = document.createElement("section");
      dependenciesPanel.className = "card formation-tab-panel";
      dependenciesPanel.dataset.formationPanel = "dependencies";
      dependenciesPanel.id = `formation-dependencies-${selected.id}`;
      dependenciesPanel.setAttribute("role", "tabpanel");
      dependenciesPanel.setAttribute("aria-labelledby", `formation-tab-dependencies-${selected.id}`);
      dependenciesPanel.innerHTML = panelTitle("DEPENDÊNCIAS", "O que depende desta formação", "Consulte a prévia antes de arquivar ou excluir. Nenhum dado é alterado nesta tela.", `<button class="button primary" type="button" data-formation-dependencies="${selected.id}">Consultar dependências</button>`);

      const settingsPanel = document.createElement("section");
      settingsPanel.className = "card formation-tab-panel formation-settings-card";
      settingsPanel.dataset.formationPanel = "settings";
      settingsPanel.id = `formation-settings-${selected.id}`;
      settingsPanel.setAttribute("role", "tabpanel");
      settingsPanel.setAttribute("aria-labelledby", `formation-tab-settings-${selected.id}`);
      settingsPanel.innerHTML = `${panelTitle("CONFIGURAÇÕES", "Gerenciar formação", isArchived ? "A formação está arquivada. Restaure-a para voltar a alterar a grade." : "Alterações de nome, período e prioridade continuam usando os mesmos dados da formação.")}
        <div class="formation-details"><span class="tag">Prioridade de foco ${selected.focus_priority}/5</span>${selected.start_date || selected.expected_end_date ? `<span class="muted">${esc(selected.start_date || "—")} → ${esc(selected.expected_end_date || "—")}</span>` : ""}</div>
        <div class="action-group">${isArchived ? `<button class="button primary" type="button" data-restore-formation="${selected.id}">Restaurar formação</button>` : `<button class="button" type="button" data-edit-formation="${selected.id}">Editar formação</button><button class="button" type="button" data-archive-formation="${selected.id}">Arquivar formação</button>`}<button class="button danger" type="button" data-delete-formation="${selected.id}">Excluir formação</button></div>`;

      const tabs = document.createElement("nav");
      tabs.className = "formation-detail-tabs";
      tabs.setAttribute("aria-label", "Seções da formação");
      tabs.setAttribute("role", "tablist");
      tabs.innerHTML = [["overview", "Visão geral"], ["curriculum", "Grade curricular"], ["dependencies", "Dependências"], ["settings", "Configurações"]].map(([value, text]) => `<button id="formation-tab-${value}-${selected.id}" type="button" role="tab" data-formation-tab="${value}" aria-controls="formation-${value}-${selected.id}" aria-selected="false">${text}</button>`).join("");
      detailStack.prepend(tabs);
      detailStack.append(dependenciesPanel, settingsPanel);

      const setFormationTab = tab => {
        const nextTab = ["overview", "curriculum", "dependencies", "settings"].includes(tab) ? tab : "overview";
        formationView.tab = nextTab;
        detailStack.closest(".formation-layout")?.classList.toggle("formation-curriculum-open", nextTab === "curriculum");
        detailStack.querySelectorAll("[data-formation-panel]").forEach(panel => { panel.hidden = panel.dataset.formationPanel !== nextTab; });
        tabs.querySelectorAll("[data-formation-tab]").forEach(button => {
          const active = button.dataset.formationTab === nextTab;
          button.setAttribute("aria-selected", String(active));
          button.tabIndex = active ? 0 : -1;
        });
        syncFormationLocation();
      };
      tabs.querySelectorAll("[data-formation-tab]").forEach(button => button.addEventListener("click", () => setFormationTab(button.dataset.formationTab)));
      tabs.addEventListener("keydown", event => {
        const buttons = [...tabs.querySelectorAll("[data-formation-tab]")];
        const currentIndex = buttons.indexOf(event.target.closest("[data-formation-tab]"));
        if (currentIndex < 0 || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (currentIndex + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
        const nextButton = buttons[nextIndex];
        setFormationTab(nextButton.dataset.formationTab);
        nextButton.focus();
      });
      setFormationTab(formationView.tab);
    }
    $("#formation-filter", app).onchange = event => { formationView.filter = event.target.value; formationView.selectedId = null; syncFormationLocation(); render(); };
    const controlMap = [["#curriculum-q", "q"], ["#curriculum-period", "period"], ["#curriculum-status", "academicStatus"], ["#curriculum-review", "reviewStatus"], ["#curriculum-visibility", "visibility"], ["#curriculum-sort", "sort"]];
    controlMap.forEach(([selector, key]) => $(selector, app)?.addEventListener(key === "q" ? "input" : "change", event => {
      curriculumView[key] = event.target.value;
      if (key === "visibility") return draw();
      if (key === "q") {
        window.clearTimeout(curriculumView.queryTimer);
        curriculumView.queryTimer = window.setTimeout(() => renderCurriculumResults(selected, allRows), 120);
      } else renderCurriculumResults(selected, allRows);
    }));
    app.querySelectorAll("[data-select-formation]").forEach(card => {
      const select = () => { selected = formations.find(item => item.id === Number(card.dataset.selectFormation)); formationView.selectedId = selected?.id || null; formationView.tab = "overview"; curriculumView.formationId = selected?.id || null; curriculumView.selectedIds.clear(); curriculumView.openGroups.clear(); syncFormationLocation(); draw(); };
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

function curriculumEditor(formationId, current = null) {
  const existingEffort = current?.required_study_minutes || "";
  const hasPlanningOptOut = Boolean(current && Object.prototype.hasOwnProperty.call(current, "planning_opt_out"));
  const planningIncluded = hasPlanningOptOut ? !Boolean(current.planning_opt_out) : current ? Boolean(current.planning_enabled) : true;
  const form = modal(current ? "Editar disciplina" : "Adicionar disciplina", `
    <label>Nome<input name="name" value="${esc(current?.name || "")}" required></label>
    <label>Código<input name="code" value="${esc(current?.code || "")}"></label>
    <label>Período / módulo<input name="period" value="${esc(current?.period || "")}"></label>
    <label>Data de início<input name="start_date" type="date" value="${esc(current?.start_date || "")}"></label>
    <label>Término da oferta<input name="end_date" type="date" value="${esc(current?.end_date || "")}"></label>
    <label>Prazo principal / entrega<input name="deadline_date" type="date" value="${esc(current?.deadline_date || "")}"></label>
    <label>Carga da instituição (min)<span class="field-help">Informação da grade; não é contabilizada como estudo pessoal.</span><input name="workload_minutes" type="number" min="1" value="${current?.workload_minutes || ""}"></label>
    <fieldset class="choice-list"><legend>Esforço pessoal necessário</legend><label><input type="radio" name="effort_mode" value="manual" ${existingEffort || !current ? "checked" : ""}> Definir manualmente</label><label><input type="radio" name="effort_mode" value="workload" ${!existingEffort && current?.workload_minutes ? "checked" : ""}> Usar a carga da grade como estimativa inicial</label></fieldset>
    <label>Esforço pessoal (min)<input name="required_study_minutes" type="number" min="1" value="${existingEffort}"></label>
    <label>Prioridade-base (1 a 5)<input name="priority_base" type="number" min="1" max="5" value="${current?.priority_base || 3}"></label>
    <label>Duração preferida do bloco (min)<input name="preferred_block_minutes" type="number" min="1" value="${current?.preferred_block_minutes || ""}"></label>
    <label class="toggle-row"><input name="planning_enabled" type="checkbox" ${planningIncluded ? "checked" : ""}> Incluir no planejamento quando estiver disponível <span class="field-help">A disciplina precisa continuar nos Estudos atuais para receber blocos.</span></label>
    ${weekdaysInputs(current?.allowed_weekdays)}
    <label>Nota mínima para aprovação<input name="minimum_grade" type="number" min="0" step="0.01" value="${current?.minimum_grade ?? ""}"></label>
    <label>Ordem<input name="sort_order" type="number" min="0" value="${current?.sort_order || 0}"></label>
    <label>Status<select name="academic_status">${["not_available","available","in_progress","completed","failed","locked","exempted"].map(key => `<option value="${key}" ${key===current?.academic_status?"selected":""}>${label(key)}</option>`).join("")}</select></label>
    <label>Observações<textarea name="notes">${esc(current?.notes || "")}</textarea></label>`,
  async (values, node) => {
    values.workload_minutes = values.workload_minutes ? Number(values.workload_minutes) : null;
    values.required_study_minutes = values.effort_mode === "workload" ? values.workload_minutes : values.required_study_minutes ? Number(values.required_study_minutes) : null;
    values.priority_base = Number(values.priority_base || 3);
    values.preferred_block_minutes = values.preferred_block_minutes ? Number(values.preferred_block_minutes) : null;
    values.minimum_grade = values.minimum_grade === "" ? null : Number(values.minimum_grade);
    values.sort_order = Number(values.sort_order);
    values.planning_enabled = node.querySelector('[name="planning_enabled"]').checked;
    values.allowed_weekdays = checkedWeekdays(node);
    delete values.effort_mode;
    if (current) await api(`/curriculum/${current.id}`, {method:"PATCH", body:JSON.stringify(values)});
    else await api(`/formations/${formationId}/curriculum`, {method:"POST", body:JSON.stringify(values)});
  });
  const workload = $(`[name="workload_minutes"]`, form);
  form.querySelectorAll('[name="effort_mode"]').forEach(input => input.addEventListener("change", () => {
    if (input.value === "workload" && input.checked && workload?.value) $(`[name="required_study_minutes"]`, form).value = workload.value;
  }));
}

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
  return `<details class="action-menu"><summary>Ações</summary><div class="action-menu-content"><button class="button" data-study-detail="${study.id}">Tópicos</button>${current ? `<button class="button" data-plan-study="${study.id}">Planejar sessão</button>` : ""}<button class="button" data-edit-study="${study.id}">Editar</button>${study.status === "active" ? `<button class="button" data-study-pause="${study.id}">Pausar</button>` : ""}${study.status === "paused" ? `<button class="button primary" data-study-resume="${study.id}">Continuar</button>` : ""}${canFocus ? `<button class="button primary" data-start-study-focus="${study.id}">Iniciar foco</button>` : ""}${study.origin === "curriculum" && current ? `<button class="button" data-study-finish="${study.id}">Finalizar</button><button class="button" data-study-remove-current="${study.id}">Remover dos atuais</button>` : ""}<button class="button" data-study-archive="${study.id}">Arquivar estudo</button><button class="button ghost" data-study-dependencies="${study.id}">Consultar dependências</button><button class="button danger" data-study-destroy="${study.id}">Excluir definitivamente</button></div></details>`;
}

function studyCounts(studies) {
  return {
    active: studies.filter(study => study.status === "active" && !studyVisibilityText(study)).length,
    paused: studies.filter(study => study.status === "paused" && !studyVisibilityText(study)).length,
    review: studies.filter(study => ["queued", "in_progress"].includes(study.review_status)).length,
    completed: studies.filter(study => study.status === "completed" && !studyVisibilityText(study)).length,
    archived: studies.filter(study => Boolean(studyVisibilityText(study))).length,
  };
}

function studyCardMarkup(study) {
  const reason = studyVisibilityText(study);
  const effort = study.origin === "curriculum" ? study.curriculum_required_study_minutes : study.required_study_minutes;
  const weeklyTarget = study.origin === "personal" ? study.minimum_weekly_minutes || study.weekly_goal_minutes : study.weekly_goal_minutes;
  return `<article id="study-card-${study.id}" class="card study-card study-result-card ${reason ? "is-archived" : ""} ${Number(studiesView.selectedId) === Number(study.id) ? "is-selected" : ""}">
    <div class="study-result-top"><div><div class="tag-row"><span class="tag">${study.origin === "curriculum" ? "CURRICULAR" : "PARALELO"}</span><span class="status">${label(study.status)}</span>${study.academic_status ? `<span class="status status-${esc(study.academic_status)}">${label(study.academic_status)}</span>` : ""}${study.review_status && study.review_status !== "none" ? `<span class="review-status ${study.review_status}">${curriculumReviewLabel(study.review_status)}</span>` : ""}</div><h2>${esc(study.name)}</h2><p>${esc(study.formation_name || "Estudo paralelo")}</p>${reason ? `<p class="archive-reason" role="status">${esc(reason)}. Este estudo permanece preservado, mas não entra em foco nem planejamento.</p>` : ""}</div>${studyActionMarkup(study)}</div>
    <div class="study-result-meta"><span>Prioridade ${study.priority}/5</span><span>Dificuldade ${study.difficulty}/5</span><span>Esforço ${effort ? minutesLabel(effort) : "não definido"}</span><span>${weeklyTarget ? `Meta semanal ${minutesLabel(weeklyTarget)}` : "Meta semanal não definida"}</span></div>
    <div class="progress" aria-label="${clampPercent(study.progress_percent)}% dos tópicos concluídos"><i style="width:${clampPercent(study.progress_percent)}%"></i></div>
    <div class="study-result-footer"><span class="muted">${study.completed_topics}/${study.topic_count} tópico(s) concluído(s) · domínio médio ${study.mastery_average}/5</span><span class="muted">${clampPercent(study.progress_percent)}%</span></div>
    <div id="study-topics-${study.id}"></div>
  </article>`;
}

function availableCurriculumMarkup(rows, formationName) {
  if (!studiesView.formationId) return `<section class="card available-curriculum-results"><div class="panel-heading"><div><span class="tag">COMECE PELA GRADE</span><h2>Escolha uma formação para adicionar disciplinas</h2><p class="muted">Formação ativa não coloca todas as matérias no planejamento. Selecione uma formação acima e escolha apenas a disciplina disponível ou em andamento que deseja transformar em Estudo atual.</p></div></div></section>`;
  const query = normalizedText(studiesView.q || "");
  const candidates = rows.filter(row => !isStructuralCurriculum(row) && ["available", "in_progress"].includes(row.academic_status) && !row.archived_at && !row.active_study_id && (!query || [row.name, row.code, row.period].some(value => normalizedText(value).includes(query)))).slice(0, 12);
  return `<section class="card available-curriculum-results"><div class="panel-heading"><div><span class="tag">DA GRADE PARA OS ESTUDOS</span><h2>Disciplinas prontas para estudar</h2><p class="muted">${esc(formationName || "A formação selecionada")} · disponíveis ou em andamento, mas ainda sem um estudo atual vinculado.</p></div></div>${candidates.map(row => `<div class="available-curriculum-row"><div><strong>${esc(row.name)}</strong><div class="muted">${esc(row.code || "Sem código")} · ${esc(row.period || "Sem período")} · <span class="status status-${esc(row.academic_status)}">${label(row.academic_status)}</span></div></div><button class="button" type="button" data-add-study="${row.id}" data-add-study-formation="${row.formation_id}">${row.academic_status === "in_progress" ? "Vincular aos atuais" : "Iniciar estudo"}</button></div>`).join("") || `<p class="muted">Nenhuma disciplina disponível ou em andamento corresponde à busca atual.</p>`}</section>`;
}

function studiesResultsMarkup(studies, formationName) {
  const cards = studies.map(studyCardMarkup).join("") || empty("Nenhum estudo neste filtro", studiesView.visibility === "archived" ? "Não há estudos arquivados ou ocultos por um item pai." : "Adicione uma disciplina da grade ou crie um assunto paralelo.");
  return `<div class="study-results">${cards}</div>${availableCurriculumMarkup(studiesView.curriculumRows || [], formationName)}`;
}

const topicStatuses = ["not_started", "in_progress", "completed", "paused", "for_review"];
const topicWeights = [[1, "Simples"], [2, "Normal"], [3, "Complexo"]];

function topicRowsFor(detail) {
  const rows = detail?.topic_effort?.topics || detail?.effort_distribution?.topics || detail?.contents || [];
  const unique = new Map();
  rows.filter(item => item?.id).forEach(item => unique.set(Number(item.id), item));
  return [...unique.values()].sort((left, right) => Number(left.sort_order || 0) - Number(right.sort_order || 0) || Number(left.id) - Number(right.id));
}

function topicOwnerEndpoints(detail) {
  const summary = detail?.topic_effort || detail?.effort_distribution || {};
  const curriculumId = Number(summary.owner_kind === "curriculum" ? summary.owner_id : detail?.curriculum_subject_id || detail?.curriculum?.id || 0);
  if (curriculumId) {
    return {
      kind: "curriculum",
      id: curriculumId,
      distribution: `/curriculum/${curriculumId}/contents/distribution`,
      reorder: `/curriculum/${curriculumId}/contents/reorder`,
    };
  }
  const studyId = Number(summary.owner_id || detail?.id || 0);
  if (!studyId) throw new Error("Não foi possível identificar a disciplina dona destes tópicos.");
  return {
    kind: "study",
    id: studyId,
    distribution: `/studies/${studyId}/topics/distribution`,
    reorder: `/studies/${studyId}/topics/reorder`,
  };
}

function topicDisplayStatus(topic) { return topic?.archived_at ? "Arquivado" : label(topic?.status); }
function topicWeightLabel(value) { return ({1:"simples", 2:"normal", 3:"complexo"}[Number(value)] || "normal"); }
function topicMetric(labelText, value) { return `<span><small>${esc(labelText)}</small><strong>${esc(value)}</strong></span>`; }
function topicDate(value) { return value ? formatLocalDate(value, {day:"2-digit", month:"2-digit", year:"numeric"}) : "—"; }

function topicPrerequisiteText(topic, allTopics) {
  const names = (topic.prerequisite_topic_ids || []).map(id => allTopics.find(item => Number(item.id) === Number(id))?.name).filter(Boolean);
  return names.length ? `Depende de ${names.join(", ")}` : "Sem pré-requisito";
}

function topicReviewText(topic) {
  const values = [];
  if (topic.status === "for_review" || Number(topic.review_requested)) values.push("Revisão indicada");
  if (Number(topic.pending_review_count)) values.push(`${topic.pending_review_count} revisão(ões) pendente(s)`);
  if (topic.next_review_date) values.push(`próxima em ${topicDate(topic.next_review_date)}`);
  return values.join(" · ");
}

function topicGroupsFor(detail, topics) {
  const groupNames = new Map((detail.groups || []).map(group => [Number(group.id), group.name]));
  const grouped = new Map();
  topics.forEach(topic => {
    const name = topic.unit || groupNames.get(Number(topic.group_id)) || "Sem unidade";
    if (!grouped.has(name)) grouped.set(name, []);
    grouped.get(name).push(topic);
  });
  return [...grouped.entries()].map(([name, rows]) => ({name, topics:rows}));
}

function topicEffortSummaryMarkup(summary, ownerId, ownerKind = "study") {
  if (!summary) return "";
  const hasTotal = summary.required_study_minutes !== null && summary.required_study_minutes !== undefined;
  const total = hasTotal ? minutesLabel(summary.required_study_minutes) : "Não definido";
  const distributed = minutesLabel(summary.distributed_minutes || 0);
  const undistributed = hasTotal ? minutesLabel(summary.undistributed_minutes || 0) : "Defina o esforço";
  const warning = Number(summary.over_distributed_minutes || 0) > 0 ? `<p class="planning-deficit">As estimativas excedem o esforço total em ${minutesLabel(summary.over_distributed_minutes)}. Revise antes de salvar.</p>` : "";
  const actionAttribute = ownerKind === "curriculum" ? "data-curriculum-topic-distribution" : "data-topic-distribution";
  const actions = hasTotal && (summary.topics || []).length ? `<div class="topic-effort-actions"><button type="button" class="button ghost" ${actionAttribute}="${ownerId}" data-topic-distribution-mode="proportional">Dividir igualmente</button><button type="button" class="button ghost" ${actionAttribute}="${ownerId}" data-topic-distribution-mode="weight">Distribuir por peso</button><button type="button" class="button" ${actionAttribute}="${ownerId}" data-topic-distribution-mode="manual">Distribuir manualmente</button></div>` : "";
  return `<section class="topic-effort-summary" aria-label="Resumo da distribuição de esforço"><div class="topic-effort-heading"><div><span class="tag">DISTRIBUIÇÃO DO ESFORÇO</span><p class="muted">As estimativas dos tópicos dividem o esforço pessoal da disciplina; elas não criam uma segunda carga de horas.</p></div></div><div class="topic-effort-values">${topicMetric("Esforço total", total)}${topicMetric("Distribuído entre tópicos", distributed)}${topicMetric("Ainda não distribuído", undistributed)}</div>${warning}${actions}</section>`;
}

function studyTopicMarkup(topic, studyId, allTopics, index, total) {
  const effectiveEstimate = topic.effective_estimated_minutes ?? topic.estimated_minutes;
  const estimate = effectiveEstimate === null || effectiveEstimate === undefined ? "—" : minutesLabel(effectiveEstimate);
  const estimateCaption = topic.estimated_minutes ? "Estimativa" : effectiveEstimate !== null && effectiveEstimate !== undefined ? "Sugestão" : "Estimativa";
  const review = topicReviewText(topic);
  const dates = [topic.started_at ? `Início ${topicDate(topic.started_at)}` : "", topic.completed_at ? `Concluído em ${topicDate(topic.completed_at)}` : ""].filter(Boolean).join(" · ");
  const progress = topic.effort_progress_percent;
  const delta = Number(topic.estimate_delta_minutes || 0);
  const hasNext = index < total - 1;
  const hasPrevious = index > 0;
  return `<article class="study-topic-row" data-topic-row="${topic.id}"><div class="study-topic-main"><div class="tag-row"><span class="status">${esc(topicDisplayStatus(topic))}</span>${review ? `<span class="review-status queued">${esc(review)}</span>` : ""}</div><strong>${esc(topic.name)}</strong><p class="muted">${esc(topic.unit || "Sem unidade")} · ordem ${index + 1} · peso ${topicWeightLabel(topic.effort_weight)}</p>${topic.description ? `<p class="field-help">${esc(topic.description)}</p>` : ""}<div class="topic-metric-grid">${topicMetric(estimateCaption, estimate)}${topicMetric("Tempo real", minutesLabel(topic.real_minutes || 0))}${topicMetric("Futuro planejado", minutesLabel(topic.future_planned_minutes || 0))}${topicMetric("Restante", topic.remaining_minutes === null || topic.remaining_minutes === undefined ? "—" : minutesLabel(topic.remaining_minutes))}${topicMetric("Sessões", `${topic.session_count || 0}`)}${topicMetric("Domínio", `${topic.mastery ?? 0}/5`)}${topicMetric("Dificuldade", topic.difficulty ? `${topic.difficulty}/5` : "—")}</div>${progress !== null && progress !== undefined ? `<div class="topic-progress-line"><div class="progress" aria-label="${clampPercent(progress)}% do esforço do tópico"><i style="width:${clampPercent(progress)}%"></i></div><span>${clampPercent(progress)}% do esforço</span></div>` : ""}<div class="topic-context"><span>${esc(topicPrerequisiteText(topic, allTopics))}</span><span>Última atividade ${esc(topicDate(topic.last_activity || topic.last_session_date))}</span>${dates ? `<span>${esc(dates)}</span>` : ""}</div>${topic.observations ? `<p class="topic-observations"><strong>Observações:</strong> ${esc(topic.observations)}</p>` : ""}${topic.status === "completed" && Number(topic.economy_minutes || 0) ? `<p class="topic-positive">Concluído com ${minutesLabel(topic.economy_minutes)} de folga sobre a estimativa.</p>` : ""}${delta > 0 ? `<p class="planning-deficit">${minutesLabel(delta)} acima da estimativa. O tópico permanece em andamento até você concluí-lo.</p>` : ""}</div><div class="study-topic-actions"><button type="button" class="button ghost" data-topic-move="up" data-topic-study="${studyId}" data-topic-id="${topic.id}" ${hasPrevious ? "" : "disabled"} aria-label="Mover ${esc(topic.name)} para cima">↑</button><button type="button" class="button ghost" data-topic-move="down" data-topic-study="${studyId}" data-topic-id="${topic.id}" ${hasNext ? "" : "disabled"} aria-label="Mover ${esc(topic.name)} para baixo">↓</button><button type="button" class="button ghost" data-plan-study-topic="${studyId}" data-topic-id="${topic.id}">Planejar</button><button type="button" class="button ghost" data-edit-study-topic="${topic.id}" data-topic-study="${studyId}">Editar</button>${topic.status !== "completed" ? `<button type="button" class="button" data-complete-study-topic="${topic.id}" data-topic-study="${studyId}">Concluir</button>` : ""}<button type="button" class="button ghost" data-archive-study-topic="${topic.id}" data-topic-study="${studyId}">Arquivar</button></div></article>`;
}

function topicDistributionPayload(form, apply) {
  const mode = $("[name=topic_distribution_mode]", form)?.value || "proportional";
  const payload = {mode, apply};
  if (mode === "manual") {
    payload.estimates = Object.fromEntries([...form.querySelectorAll("[data-topic-manual-estimate]")].map(input => [input.dataset.topicManualEstimate, input.value === "" ? null : Number(input.value)]));
  }
  return payload;
}

function topicDistributionPreviewMarkup(result) {
  const rows = result?.proposed_estimates || [];
  if (!rows.length) return "<p class=\"muted\">Escolha uma forma de distribuição para ver a prévia.</p>";
  return `<div class="topic-distribution-preview"><div class="topic-effort-values">${topicMetric("Esforço total", minutesLabel(result.required_study_minutes))}${topicMetric("Distribuído", minutesLabel(result.distributed_minutes))}${topicMetric("Não distribuído", minutesLabel(result.undistributed_minutes))}</div><ul>${rows.map(row => `<li><span>${esc(row.name)}</span><strong>${minutesLabel(row.estimated_minutes)}</strong></li>`).join("")}</ul></div>`;
}

function openTopicDistributionDialog(detail, opener = null, preferredMode = "proportional") {
  const topics = topicRowsFor(detail);
  const owner = topicOwnerEndpoints(detail);
  if (!topics.length) return toast("Cadastre ao menos um tópico antes de distribuir o esforço.");
  const summary = detail.topic_effort || detail.effort_distribution || {};
  if (summary.required_study_minutes === null || summary.required_study_minutes === undefined) return toast("Defina o esforço pessoal total da disciplina antes de distribuí-lo.");
  const form = modal(`Distribuir esforço · ${esc(detail.name || detail.curriculum?.name || "disciplina")}`, `<p class="muted">Revise a prévia antes de aplicar. A soma nunca poderá ultrapassar ${minutesLabel(summary.required_study_minutes)}.</p><label>Como distribuir<select name="topic_distribution_mode">${[["proportional", "Igualmente entre os tópicos"], ["weight", "Proporcional ao peso"], ["manual", "Manual, por tópico"]].map(([value, text]) => `<option value="${value}" ${value === preferredMode ? "selected" : ""}>${text}</option>`).join("")}</select></label><p class="field-help" data-topic-distribution-help>Pesos: simples = 1, normal = 2 e complexo = 3.</p><section class="topic-manual-estimates" data-topic-manual-estimates hidden>${topics.map(topic => `<label>${esc(topic.name)}<input type="number" min="0" name="topic-estimate-${topic.id}" data-topic-manual-estimate="${topic.id}" value="${topic.estimated_minutes ?? ""}" placeholder="minutos"></label>`).join("")}</section><div class="topic-distribution-preview" data-topic-distribution-preview aria-live="polite">Carregando prévia…</div>`, async (_values, currentForm) => {
    await api(owner.distribution, {method:"POST", body:JSON.stringify(topicDistributionPayload(currentForm, true))});
  });
  form.dataset.successMessage = "Distribuição de esforço atualizada.";
  $(".button.primary", form).textContent = "Aplicar distribuição";
  const modeInput = $("[name=topic_distribution_mode]", form);
  const manual = $("[data-topic-manual-estimates]", form);
  const preview = $("[data-topic-distribution-preview]", form);
  const refreshPreview = async () => {
    if (!form.isConnected) return;
    manual.hidden = modeInput.value !== "manual";
    try {
      const result = await api(owner.distribution, {method:"POST", body:JSON.stringify(topicDistributionPayload(form, false))});
      if (form.isConnected) preview.innerHTML = topicDistributionPreviewMarkup(result);
    } catch (error) {
      if (form.isConnected) preview.innerHTML = `<p class="planning-deficit">${esc(error.message || "Não foi possível calcular a distribuição.")}</p>`;
    }
  };
  modeInput.addEventListener("change", refreshPreview);
  manual.addEventListener("input", () => { if (modeInput.value === "manual") window.clearTimeout(manual.dataset.previewTimer); manual.dataset.previewTimer = window.setTimeout(refreshPreview, 180); });
  refreshPreview();
  if (opener) window.setTimeout(() => modeInput.focus(), 0);
  return form;
}

async function openTopicDistribution(studyId, opener = null, preferredMode = "proportional") {
  return openTopicDistributionDialog(await api(`/studies/${studyId}`), opener, preferredMode);
}

async function openCurriculumTopicDistribution(curriculumId, opener = null, preferredMode = "proportional") {
  const data = await api(`/curriculum/${curriculumId}/contents`);
  return openTopicDistributionDialog({
    name:data.curriculum?.name,
    curriculum_subject_id:curriculumId,
    curriculum:data.curriculum,
    contents:data.contents,
    effort_distribution:data.effort_distribution,
  }, opener, preferredMode);
}

async function moveTopic(detail, topicId, direction) {
  const topics = topicRowsFor(detail);
  const index = topics.findIndex(topic => Number(topic.id) === Number(topicId));
  const targetIndex = index + (direction === "up" ? -1 : 1);
  if (index < 0 || targetIndex < 0 || targetIndex >= topics.length) return;
  [topics[index], topics[targetIndex]] = [topics[targetIndex], topics[index]];
  await api(topicOwnerEndpoints(detail).reorder, {method:"POST", body:JSON.stringify({topic_ids:topics.map(topic => topic.id)})});
  toast("Ordem dos tópicos atualizada.");
  return render();
}

async function moveStudyTopic(studyId, topicId, direction) {
  return moveTopic(await api(`/studies/${studyId}`), topicId, direction);
}

async function moveCurriculumTopic(curriculumId, topicId, direction) {
  const data = await api(`/curriculum/${curriculumId}/contents`);
  return moveTopic({
    curriculum_subject_id:curriculumId,
    curriculum:data.curriculum,
    contents:data.contents,
    topic_effort:data.effort_distribution,
  }, topicId, direction);
}

async function renderStudyTopics(studyId) {
  const holder = $(`#study-topics-${studyId}`, app);
  if (!holder) return;
  holder.innerHTML = `<section class="topic-panel" aria-busy="true" role="status">Carregando tópicos…</section>`;
  const detail = await api(`/studies/${studyId}`);
  const topics = topicRowsFor(detail);
  const indexById = new Map(topics.map((topic, index) => [Number(topic.id), index]));
  const groups = topicGroupsFor(detail, topics);
  holder.innerHTML = `<section class="topic-panel" aria-label="Tópicos de ${esc(detail.name)}"><div class="bar"><div><span class="tag">TÓPICOS DO ESTUDO</span><p class="muted">Cada tópico é uma unidade concreta do planejamento. A ordem, as dependências e o esforço guiam a próxima sessão.</p></div><div class="action-group"><button type="button" class="button" data-plan-study="${detail.id}">Planejar sessão</button><button type="button" class="button primary" data-new-topic="${detail.id}">+ Adicionar tópico</button></div></div>${topicEffortSummaryMarkup(detail.topic_effort, detail.id)}${groups.map(group => `<section class="study-topic-group"><h3>${esc(group.name)}</h3>${group.topics.map(topic => studyTopicMarkup(topic, detail.id, topics, indexById.get(Number(topic.id)), topics.length)).join("")}</section>`).join("") || empty("Sem tópicos", "Adicione as unidades ou tópicos que você pretende estudar nesta disciplina.", `<button type="button" class="button primary" data-new-topic="${detail.id}">+ Adicionar tópico</button>`)}</section>`;
}

async function studyTopicEditor(studyId, current = null) {
  studiesView.selectedId = Number(studyId);
  studiesView.expandedStudyId = Number(studyId);
  studiesView.panel = "topics";
  syncStudiesLocation();
  const detail = await api(`/studies/${studyId}`);
  const topics = topicRowsFor(detail);
  const fresh = current ? topics.find(topic => Number(topic.id) === Number(current.id)) || current : null;
  const prerequisites = new Set((fresh?.prerequisite_topic_ids || []).map(Number));
  const candidates = topics.filter(topic => Number(topic.id) !== Number(fresh?.id));
  const form = modal(fresh ? "Editar tópico" : "Adicionar tópico", `<label>Título<input name="name" value="${esc(fresh?.name || "")}" required></label><label>Unidade / módulo<input name="unit" value="${esc(fresh?.unit || "")}" placeholder="Ex.: Módulo 1"></label><label>Descrição<textarea name="description">${esc(fresh?.description || "")}</textarea></label><div class="settings-grid"><label>Tempo estimado (min)<input name="estimated_minutes" type="number" min="1" value="${fresh?.estimated_minutes ?? ""}" placeholder="Divide o esforço total"></label><label>Peso<select name="effort_weight">${topicWeights.map(([value, text]) => `<option value="${value}" ${Number(fresh?.effort_weight || 2) === value ? "selected" : ""}>${text}</option>`).join("")}</select></label><label>Domínio (0–5)<input name="mastery" type="number" min="0" max="5" value="${fresh?.mastery ?? 0}"></label><label>Dificuldade (1–5)<input name="difficulty" type="number" min="1" max="5" value="${fresh?.difficulty ?? ""}"></label><label>Ordem<input name="sort_order" type="number" min="0" value="${fresh?.sort_order ?? topics.length}"></label></div><label>Status<select name="status">${topicStatuses.map(value => `<option value="${value}" ${value === (fresh?.status || "not_started") ? "selected" : ""}>${label(value)}</option>`).join("")}</select></label><label class="toggle-row"><input name="review_requested" type="checkbox" value="true" ${Number(fresh?.review_requested) || fresh?.status === "for_review" ? "checked" : ""}> Indicar este tópico para revisão</label><label>Ao concluir com blocos automáticos futuros<select name="future_blocks_action"><option value="">Perguntar antes de concluir</option><option value="next_topic">Avançar ao próximo tópico</option><option value="replan">Cancelar automáticos e replanejar</option><option value="review">Manter como revisão</option></select></label><label>Observações<textarea name="observations" placeholder="Dúvidas, materiais e próximo passo.">${esc(fresh?.observations || "")}</textarea></label><fieldset class="choice-list"><legend>Pré-requisitos (opcional)</legend>${candidates.length ? candidates.map(topic => `<label><input type="checkbox" name="prerequisite_topic_id" value="${topic.id}" ${prerequisites.has(Number(topic.id)) ? "checked" : ""}> ${esc(topic.name)}<span>${esc(topic.unit || "Sem unidade")} · ${topicDisplayStatus(topic)}</span></label>`).join("") : "<p class=\"muted\">Ainda não há outro tópico desta disciplina.</p>"}</fieldset>`, async (values, editorForm) => {
    const payload = {
      ...values,
      sort_order:Number(values.sort_order || 0),
      mastery:Number(values.mastery || 0),
      difficulty:values.difficulty === "" ? null : Number(values.difficulty),
      estimated_minutes:values.estimated_minutes === "" ? null : Number(values.estimated_minutes),
      effort_weight:Number(values.effort_weight || 2),
      review_requested:editorForm.querySelector("[name=review_requested]")?.checked || false,
      prerequisite_topic_ids:[...editorForm.querySelectorAll("[name=prerequisite_topic_id]:checked")].map(input => Number(input.value)),
    };
    delete payload.prerequisite_topic_id;
    if (fresh) await api(`/topics/${fresh.id}`, {method:"PATCH", body:JSON.stringify(payload)});
    else await api(`/studies/${studyId}/topics`, {method:"POST", body:JSON.stringify(payload)});
  });
  $(".button.primary", form).textContent = fresh ? "Salvar tópico" : "Adicionar tópico";
  return form;
}

async function completeStudyTopic(topicId, studyId) {
  const finish = action => api(`/topics/${topicId}`, {
    method:"PATCH", body:JSON.stringify({status:"completed", future_blocks_action:action || null}),
  });
  try {
    await finish();
    studiesView.selectedId = Number(studyId);
    studiesView.expandedStudyId = Number(studyId);
    studiesView.panel = "topics";
    toast("Tópico concluído.");
    return render();
  } catch (error) {
    if (error.code !== "future_topic_blocks_need_resolution") throw error;
    const automatic = error.details?.automatic_blocks || [];
    const manual = error.details?.manual_blocks || [];
    const form = modal(
      "Concluir tópico e tratar blocos futuros",
      `<p class="muted">Há ${automatic.length} bloco(s) automático(s) futuro(s) ligado(s) a este tópico. Escolha o destino antes de concluir. ${manual.length ? `${manual.length} bloco(s) manual(is) serão preservados sem alteração.` : "Não há bloco manual para alterar."}</p><label>Destino dos blocos automáticos<select name="future_blocks_action" required><option value="next_topic">Avançar para o próximo tópico elegível</option><option value="replan">Cancelar automáticos e propor novo planejamento</option><option value="review">Manter como revisão deste tópico</option></select></label>`,
      async values => {
        await finish(values.future_blocks_action);
        studiesView.selectedId = Number(studyId);
        studiesView.expandedStudyId = Number(studyId);
        studiesView.panel = "topics";
      },
    );
    $(".button.primary", form).textContent = "Concluir tópico";
    return form;
  }
}

async function refreshStudiesSearchResults(formationName) {
  const revision = ++studiesView.searchRevision;
  const parameters = new URLSearchParams({visibility:studiesView.visibility, formation_id:studiesView.formationId, q:studiesView.q});
  const payload = await api(`/studies?${parameters}`);
  if (revision !== studiesView.searchRevision || page !== "studies") return;
  const studies = asRows(payload);
  studiesView.rows = studies;
  syncStudiesLocation();
  const result = $("#studies-results", app);
  if (result) result.innerHTML = studiesResultsMarkup(studies, formationName);
  const expanded = studiesView.expandedStudyId || (studiesView.panel === "topics" ? studiesView.selectedId : null);
  if (expanded && studies.some(study => Number(study.id) === Number(expanded))) renderStudyTopics(expanded).catch(error => toast(error.message));
  const summary = $("#studies-summary-count", app);
  if (summary) summary.textContent = `${studies.length} estudo(s) nos filtros atuais.`;
}

async function renderStudies() {
  const parameters = new URLSearchParams({visibility:studiesView.visibility, formation_id:studiesView.formationId, q:studiesView.q});
  const countParameters = new URLSearchParams({visibility:"all", formation_id:studiesView.formationId});
  const [payload, allPayload, formations, curriculumPayload] = await Promise.all([
    api(`/studies?${parameters}`),
    api(`/studies?${countParameters}`),
    api("/formations?state=all"),
    studiesView.formationId ? api(`/formations/${Number(studiesView.formationId)}/curriculum`).catch(() => []) : Promise.resolve([]),
  ]);
  const studies = asRows(payload);
  const formation = formations.find(item => String(item.id) === String(studiesView.formationId));
  studiesView.rows = studies;
  studiesView.curriculumRows = asRows(curriculumPayload);
  syncStudiesLocation();
  const counts = studyCounts(asRows(allPayload));
  const filters = [["active", "Ativos"], ["paused", "Pausados"], ["review", "Para revisar"], ["completed", "Concluídos"], ["archived", "Arquivados"], ["all", "Todos"]];
  app.innerHTML = `<section class="studies-shell"><div class="bar"><div><span class="tag">ESTUDOS ATUAIS</span><p class="muted"><span id="studies-summary-count">${studies.length} estudo(s) nos filtros atuais.</span> Estudos sob formação ou disciplina arquivada aparecem em Arquivados, com o motivo.</p></div><button class="button primary" data-new-study>Novo estudo paralelo</button></div><section class="study-controls" aria-label="Filtros de estudos"><div class="quick-filter-list" role="group" aria-label="Filtro de situação">${filters.map(([value, title]) => `<button class="filter-pill ${studiesView.visibility === value ? "active" : ""}" type="button" data-study-filter="${value}" aria-pressed="${studiesView.visibility === value}">${title}${value !== "all" ? ` <span>${counts[value] || 0}</span>` : ""}</button>`).join("")}</div><label>Formação<select id="study-formation-filter"><option value="">Todas</option>${formations.map(item => `<option value="${item.id}" ${String(studiesView.formationId) === String(item.id) ? "selected" : ""}>${esc(item.name)}${item.archived_at ? " · arquivada" : ""}</option>`).join("")}</select></label><label>Pesquisar<input id="study-q" value="${esc(studiesView.q)}" placeholder="Nome da matéria ou estudo" autocomplete="off"></label></section><div id="studies-results">${studiesResultsMarkup(studies, formation?.name)}</div></section>`;
  const expanded = studiesView.expandedStudyId || (studiesView.panel === "topics" ? studiesView.selectedId : null);
  if (expanded && studies.some(study => Number(study.id) === Number(expanded))) renderStudyTopics(expanded).catch(error => toast(error.message));
  app.querySelectorAll("[data-study-filter]").forEach(button => button.addEventListener("click", () => { studiesView.visibility = button.dataset.studyFilter; studiesView.selectedId = null; studiesView.expandedStudyId = null; studiesView.panel = ""; syncStudiesLocation(); render(); }));
  $("#study-formation-filter", app)?.addEventListener("change", event => { studiesView.formationId = event.target.value; studiesView.selectedId = null; studiesView.expandedStudyId = null; studiesView.panel = ""; studiesView.searchRevision += 1; syncStudiesLocation(); render(); });
  $("#study-q", app)?.addEventListener("input", event => {
    studiesView.q = event.target.value;
    window.clearTimeout(studiesView.queryTimer);
    studiesView.queryTimer = window.setTimeout(() => refreshStudiesSearchResults(formation?.name).catch(error => toast(error.message || "Não foi possível atualizar a busca.")), 220);
  });
}

function reviewStageText(value) {
  return {d1:"D+1 · primeira revisão", d7:"D+7 · segunda revisão", d30:"D+30 · consolidação"}[value] || "Revisão";
}

async function renderReviews() {
  const reviews = await api("/reviews");
  const today = saoPauloTodayISO();
  const nextSeven = calendarISO(calendarAddDays(calendarDateFromISO(today), 6));
  const overdue = reviews.filter(item => item.due_date < today);
  const dueToday = reviews.filter(item => item.due_date === today);
  const upcoming = reviews.filter(item => item.due_date >= today && item.due_date <= nextSeven);
  const byFilter = {today:dueToday, upcoming, overdue};
  const visible = byFilter[reviewsView.filter] || dueToday;
  const filters = [["today", "Hoje", dueToday.length], ["upcoming", "Próximos 7 dias", upcoming.length], ["overdue", "Atrasadas", overdue.length]];
  app.innerHTML = `<section class="reviews-shell"><div class="grid kpis">${statCard("Pendentes", reviews.length, "cadeias de revisão ativas", "⌛", "blue")}${statCard("Atrasadas", overdue.length, overdue.length ? "priorize o que ficou para trás" : "nenhuma revisão vencida", "!", "rose")}${statCard("Próximos 7 dias", upcoming.length, "inclui as revisões de hoje", "▣", "green")}</div><section class="grid analytics-layout"><section class="card"><div class="panel-heading"><div><span class="tag">FILA DE REVISÃO</span><h2>O que precisa ser lembrado</h2><p class="muted">Escolha uma avaliação após revisar. A próxima data é calculada pela estratégia já configurada.</p></div></div><div class="content-tabs" role="group" aria-label="Filtro de revisões">${filters.map(([value, text, total]) => `<button type="button" data-review-filter="${value}" aria-pressed="${reviewsView.filter === value}">${text} <span>${total}</span></button>`).join("")}</div><div class="review-queue">${visible.map(item => `<article class="review-queue-item"><div><strong>${esc(item.topic_name)}</strong><div class="muted">${esc(item.subject_name)} · prevista para ${formatLocalDate(item.due_date, {day:"2-digit", month:"short"})}</div><span class="review-stage">${reviewStageText(item.review_stage)}</span></div><div class="review-buttons" aria-label="Avaliar revisão de ${esc(item.topic_name)}">${[["wrong","Errei"],["hard","Difícil"],["good","Fui bem"],["easy","Fácil"]].map(([rating,text])=>`<button class="button" data-review="${item.id}" data-rating="${rating}">${text}</button>`).join("")}</div></article>`).join("") || empty(reviewsView.filter === "overdue" ? "Nenhuma revisão atrasada" : "Nenhuma revisão neste recorte", reviewsView.filter === "today" ? "As revisões surgem depois de uma sessão com conteúdo." : "Mude o recorte para consultar as demais revisões pendentes.")}</div></section><aside class="card"><div class="panel-heading"><div><span class="tag">COMO FUNCIONA</span><h2>Revisão espaçada</h2></div></div><div class="stack"><div><strong>D+1</strong><p class="muted">Reforça o conteúdo depois da primeira sessão.</p></div><div><strong>D+7</strong><p class="muted">Consolida a lembrança após uma boa revisão inicial.</p></div><div><strong>D+30</strong><p class="muted">Ajuda a manter o conteúdo em longo prazo.</p></div></div></aside></section></section>`;
  app.querySelectorAll("[data-review-filter]").forEach(button => button.addEventListener("click", () => { reviewsView.filter = button.dataset.reviewFilter; renderReviews(); }));
}

function historyRangeDates() {
  const today = calendarDateFromISO(saoPauloTodayISO());
  if (historyView.range === "all") return {start:"", end:"", label:"Sessões mais recentes"};
  const days = Number(historyView.range || 30);
  return {start:calendarISO(calendarAddDays(today, -(days - 1))), end:calendarISO(today), label:`Últimos ${days} dias`};
}

function historyEntryLabel(value) { return {review:"Revisão", timer:"Timer", manual:"Manual"}[value] || "Sessão"; }

function historyTimeRange(row) {
  if (!row.started_at || !row.ended_at) return "—";
  const options = {hour:"2-digit", minute:"2-digit", timeZone:"America/Sao_Paulo"};
  return `${new Intl.DateTimeFormat("pt-BR", options).format(new Date(row.started_at))}–${new Intl.DateTimeFormat("pt-BR", options).format(new Date(row.ended_at))}`;
}

function historyRowsMarkup(rows) {
  return rows.map(row => `<tr><td>${formatLocalDate(row.date, {day:"2-digit", month:"2-digit", year:"numeric"})}</td><td><strong>${esc(row.subject_name)}</strong><div class="muted">${esc(row.topic_name || "Sem tópico")}</div></td><td><span class="status">${historyEntryLabel(row.entry_method)}</span></td><td>${hours(row.duration_seconds)}</td><td>${historyTimeRange(row)}</td><td><button class="button ghost" data-delete-session="${row.id}">Excluir</button></td></tr>`).join("");
}

function filterHistoryRows(rows) {
  const query = String(historyView.query || "").trim().toLocaleLowerCase("pt-BR");
  if (!query) return rows;
  return rows.filter(row => [row.subject_name, row.topic_name, historyEntryLabel(row.entry_method), row.date].some(value => String(value || "").toLocaleLowerCase("pt-BR").includes(query)));
}

async function renderHistory() {
  const range = historyRangeDates();
  const query = new URLSearchParams();
  if (range.start) query.set("start", range.start);
  if (range.end) query.set("end", range.end);
  const rows = await api(`/sessions${query.toString() ? `?${query}` : ""}`);
  historyView.rows = rows;
  const visible = filterHistoryRows(rows);
  const totalSeconds = rows.reduce((total, row) => total + Number(row.duration_seconds || 0), 0);
  const days = new Set(rows.map(row => row.date)).size;
  const subjects = new Set(rows.map(row => row.subject_name).filter(Boolean)).size;
  app.innerHTML = `<section class="history-shell"><div class="bar"><div><span class="tag">HISTÓRICO REAL</span><h2>O que foi realmente estudado</h2><p class="muted">${range.label}. Planejamento e estudo realizado continuam separados.</p></div><div class="action-group"><button class="button" data-export>Exportar CSV</button><button class="button primary" data-manual>Registrar sessão</button></div></div><div class="history-summary">${statCard("Tempo no período", hours(totalSeconds), "sessões reais registradas", "ϟ", "violet")}${statCard("Sessões", rows.length, "neste recorte", "▣", "blue")}${statCard("Dias estudados", days, "datas com atividade", "◷", "green")}${statCard("Matérias", subjects, "com tempo real", "◉", "amber")}</div><section class="card"><div class="history-filters"><div class="content-tabs" role="group" aria-label="Período do histórico">${[["7","7 dias"],["30","30 dias"],["all","Recentes"]].map(([value,text]) => `<button type="button" data-history-range="${value}" aria-pressed="${historyView.range === value}">${text}</button>`).join("")}</div><label>Buscar no período carregado<input id="history-q" value="${esc(historyView.query)}" placeholder="Matéria, tópico, tipo ou data" autocomplete="off"></label></div><div class="table-wrap"><table class="table"><thead><tr><th>Data</th><th>Matéria / tópico</th><th>Tipo</th><th>Duração</th><th>Horário</th><th><span class="sr-only">Ações</span></th></tr></thead><tbody id="history-table-body">${historyRowsMarkup(visible)}</tbody></table></div><p id="history-result-count" class="muted">${visible.length} de ${rows.length} sessão(ões) no período carregado.</p>${!rows.length ? empty("Sem sessões neste período", "O histórico será preenchido apenas pelo que você realmente estudar.") : ""}</section></section>`;
  app.querySelectorAll("[data-history-range]").forEach(button => button.addEventListener("click", () => { historyView.range = button.dataset.historyRange; historyView.query = ""; renderHistory(); }));
  $("#history-q", app)?.addEventListener("input", event => {
    historyView.query = event.target.value;
    const filtered = filterHistoryRows(historyView.rows || []);
    $("#history-table-body", app).innerHTML = historyRowsMarkup(filtered);
    $("#history-result-count", app).textContent = `${filtered.length} de ${(historyView.rows || []).length} sessão(ões) no período carregado.`;
  });
}

async function renderAnalyticsLegacy() {
  const data = await api("/analytics");
  const distribution = Object.fromEntries((data.academic_distribution || []).map(row => [row.status, count(row.count)]));
  const formations = data.academic_progress || [];
  const missingRealSessions = count(data.completed_planned_without_real_session);
  app.innerHTML = `<div class="grid kpis">${card("Tempo real registrado", hours(data.total_seconds), "soma de sessões reais")}${card("Esta semana",hours(data.week_seconds),"sessões reais, segunda a domingo")}${card("Dias estudados",data.days_studied,"datas distintas de sessões reais")}${card("Sessões registradas",data.real_sessions ?? data.sessions,"linhas em sessões de estudo")}${card("Blocos concluídos",data.completed_planned_blocks || 0,"planejamento, não tempo real")}</div>${missingRealSessions ? `<section class="card analytics-warning" role="status"><div><span class="tag warning">REGISTRO PENDENTE</span><h2>${plural(missingRealSessions, "bloco concluído", "blocos concluídos")} sem sessão real</h2><p>Planejamento concluído não é contabilizado automaticamente como tempo estudado. Registre ou corrija a sessão para que a análise reflita o estudo real.</p></div><a class="button primary" href="/history">Registrar sessão real</a></section>` : ""}<section class="grid analytics-layout"><section class="card"><div class="bar"><div><span class="tag">PROGRESSO ACADÊMICO</span><h2>Por formação</h2></div><a class="button ghost" href="/formations">Abrir central de disciplinas</a></div>${formations.map(formation => { const progress = curriculumSummary([], formation.academic_progress || formation, formation); return `<div class="academic-formation-row"><div class="row"><strong>${esc(formation.name)}</strong><span>${progress.percent}%</span></div><div class="progress"><i style="width:${progress.percent}%"></i></div><div class="muted">${progress.completed} concluídas · ${progress.exempted} dispensadas · ${progress.inProgress} em andamento · ${progress.pending} pendentes · ${progress.review} para revisar</div></div>`; }).join("") || empty("Sem formações", "Cadastre uma formação para acompanhar o progresso acadêmico.")}</section><section class="card"><span class="tag">DISTRIBUIÇÃO</span><h2>Situação das disciplinas</h2><div class="status-distribution">${curriculumAcademicStatuses.map(value => `<div><span>${label(value)}</span><strong>${distribution[value] || 0}</strong></div>`).join("")}</div><p class="muted">Concluídas e dispensadas compõem o progresso. “Para revisar” é uma intenção paralela, mostrada dentro de cada formação.</p></section></section><section class="grid analytics-layout"><section class="card"><span class="tag">PRÓXIMAS PENDÊNCIAS</span><h2>Matérias em andamento e pendentes</h2>${(data.next_pending_subjects || []).map(row => `<div class="list-item"><div class="row"><strong>${esc(row.name)}</strong><span class="status status-${esc(row.academic_status)}">${label(row.academic_status)}</span></div><div class="muted">${esc(row.formation_name)} · ${esc(row.period || "Sem período")}${row.review_status && row.review_status !== "none" ? ` · ${curriculumReviewLabel(row.review_status)}` : ""}</div></div>`).join("") || empty("Sem pendências", "Não há disciplinas pendentes nas formações ativas.")}</section><section class="card"><h2>Horas por matéria</h2>${data.by_subject.map(row => `<div class="list-item"><div class="row"><strong>${esc(row.name)}</strong><span>${hours(row.seconds)}</span></div><div class="progress"><i style="width:${data.total_seconds ? Math.round(row.seconds/data.total_seconds*100) : 0}%"></i></div></div>`).join("") || empty("Sem dados", "Registre sessões reais para analisar seus hábitos.")}</section></section>`;
}

function analyticsDates() {
  const today = calendarDateFromISO(saoPauloTodayISO());
  if (analyticsView.range === "custom") {
    if (validCalendarDate(analyticsView.start) && validCalendarDate(analyticsView.end) && analyticsView.start <= analyticsView.end) return {start:analyticsView.start, end:analyticsView.end};
    analyticsView.range = "30";
    analyticsView.start = "";
    analyticsView.end = "";
  }
  const days = [7, 14, 30].includes(Number(analyticsView.range)) ? Number(analyticsView.range) : 30;
  return {start:calendarISO(calendarAddDays(today, -(days - 1))), end:calendarISO(today)};
}

function analyticsCapacityMarkup(capacity, days) {
  const balance = Number(capacity?.surplus_minutes || 0);
  return `<article class="capacity-card"><span class="tag">${days} DIAS</span><strong>${minutesLabel(capacity?.capacity_minutes)}</strong><span class="muted">capacidade · ${minutesLabel(capacity?.free_minutes)} livre</span><span class="${balance < 0 ? "planning-deficit" : "field-help"}">${balance < 0 ? `déficit ${minutesLabel(Math.abs(balance))}` : `folga ${minutesLabel(balance)}`}</span></article>`;
}

async function renderAnalytics() {
  const dates = analyticsDates();
  const params = new URLSearchParams({start:dates.start, end:dates.end});
  if (analyticsView.formationId) params.set("formation_id", analyticsView.formationId);
  if (analyticsView.itemId) params.set("item_id", analyticsView.itemId);
  if (analyticsView.kind) params.set("kind", analyticsView.kind);
  const today = saoPauloTodayISO();
  const monday = calendarISO(calendarMonday(calendarDateFromISO(today)));
  const monthStart = `${today.slice(0, 7)}-01`;
  const [data, dayData, weekData, monthData, formations, studies] = await Promise.all([
    api(`/analytics/workload?${params}`),
    api(`/analytics/workload?start=${today}&end=${today}`),
    api(`/analytics/workload?start=${monday}&end=${today}`),
    api(`/analytics/workload?start=${monthStart}&end=${today}`),
    api("/formations?state=all"),
    api("/studies?visibility=all"),
  ]);
  syncAnalyticsLocation();
  const completion = data.completion_rate_percent == null ? "—" : `${data.completion_rate_percent}%`;
  const effortItems = data.ideal?.items || [];
  app.innerHTML = `<section class="bar"><div><span class="tag">ANÁLISES OPERACIONAIS</span><h2>Tempo, capacidade e risco</h2><p class="muted">Sessões reais, planejamento e carga restante são mostrados separadamente. O progresso acadêmico completo permanece na Central de Disciplinas.</p></div></section><form id="analytics-filters" class="analytics-filters"><label>Período<select name="range" id="analytics-range">${[["7","7 dias"],["14","14 dias"],["30","30 dias"],["custom","Personalizado"]].map(([value,text]) => `<option value="${value}" ${analyticsView.range === value ? "selected" : ""}>${text}</option>`).join("")}</select></label><label>Início<input name="start" type="date" value="${esc(analyticsView.range === "custom" ? dates.start : analyticsView.start || dates.start)}"></label><label>Fim<input name="end" type="date" value="${esc(analyticsView.range === "custom" ? dates.end : analyticsView.end || dates.end)}"></label><label>Formação<select name="formation_id"><option value="">Todas</option>${formations.map(item => `<option value="${item.id}" ${String(analyticsView.formationId) === String(item.id) ? "selected" : ""}>${esc(item.name)}</option>`).join("")}</select></label><label>Disciplina / estudo<select name="item_id"><option value="">Todos</option>${studies.map(item => `<option value="${item.id}" ${String(analyticsView.itemId) === String(item.id) ? "selected" : ""}>${esc(item.name)}</option>`).join("")}</select></label><label>Tipo<select name="kind"><option value="">Curricular e paralelo</option><option value="curriculum" ${analyticsView.kind === "curriculum" ? "selected" : ""}>Curricular</option><option value="personal" ${analyticsView.kind === "personal" ? "selected" : ""}>Paralelo</option></select></label><button class="button primary">Aplicar filtros</button></form><div class="grid kpis">${card("Hoje", minutesLabel(dayData.total_seconds / 60), "tempo real")}${card("Esta semana", minutesLabel(weekData.total_seconds / 60), "tempo real")}${card("Este mês", minutesLabel(monthData.total_seconds / 60), "tempo real")}${card("Período filtrado", minutesLabel(data.total_seconds / 60), `${data.sessions} sessão(ões) reais`) }${card("Cumprimento", completion, `${data.planned.completed || 0}/${data.planned.total || 0} blocos concluídos`)}</div>${data.completed_planned_without_real_session ? `<section class="card analytics-warning" role="status"><div><span class="tag warning">REGISTRO PENDENTE</span><h2>${plural(data.completed_planned_without_real_session, "bloco concluído", "blocos concluídos")} sem sessão real</h2><p>Bloco concluído não reduz a carga de esforço. Registre ou corrija a sessão real para que as análises fiquem corretas.</p></div><a class="button primary" href="/history">Registrar sessão real</a></section>` : ""}<section class="card"><div class="bar"><div><span class="tag">CAPACIDADE</span><h2>Próximos horizontes</h2></div><a class="button ghost" href="/planning?tab=ideal">Abrir mundo ideal</a></div><div class="capacity-grid">${analyticsCapacityMarkup(data.capacity?.["7"], 7)}${analyticsCapacityMarkup(data.capacity?.["14"], 14)}${analyticsCapacityMarkup(data.capacity?.["30"], 30)}</div></section><section class="grid analytics-layout"><section class="card"><span class="tag">PLANEJADO X REALIZADO</span><h2>Execução do período</h2><div class="status-distribution"><div><span>Blocos previstos</span><strong>${data.planned.total || 0}</strong></div><div><span>Concluídos</span><strong>${data.planned.completed || 0}</strong></div><div><span>Cancelados</span><strong>${data.planned.cancelled || 0}</strong></div><div><span>Futuros</span><strong>${minutesLabel(data.planned.future_minutes)}</strong></div></div><p class="muted">O tempo real vem de ${data.sessions} sessão(ões) em ${data.days_studied} dia(s). Planejamento não é contabilizado como tempo estudado.</p></section><section class="card"><span class="tag">HORAS POR ITEM</span><h2>Onde o tempo foi investido</h2>${data.by_item?.map(item => `<div class="list-item"><div class="row"><strong>${esc(item.name)}</strong><span>${minutesLabel(item.seconds / 60)}</span></div><div class="progress"><i style="width:${data.total_seconds ? Math.round(item.seconds / data.total_seconds * 100) : 0}%"></i></div><div class="field-help">${item.origin === "personal" ? "Estudo paralelo" : "Disciplina curricular"} · ${item.sessions} sessão(ões)</div></div>`).join("") || empty("Sem dados no período", "Registre sessões reais para analisar a distribuição do seu tempo.")}</section></section><section class="grid analytics-layout"><section class="card"><span class="tag">ESFORÇO RESTANTE E RISCO</span><h2>Itens ativos</h2>${effortItems.length ? effortItems.map(item => `<div class="list-item"><div class="row"><strong>${esc(item.name)}</strong><span class="status">${esc(item.risk_label)}</span></div><div class="muted">Real ${minutesLabel(item.real_minutes)} · faltam ${minutesLabel(item.remaining_minutes)} · não alocado ${minutesLabel(item.unallocated_minutes)} · prioridade ${item.priority_effective}/10</div>${item.deficit_minutes ? `<div class="planning-deficit">Déficit ${minutesLabel(item.deficit_minutes)} até ${esc(item.deadline || "o prazo")}</div>` : ""}</div>`).join("") : empty("Nenhum item ativo", "Ative uma disciplina ou configure um estudo paralelo.")}</section><section class="card"><span class="tag">EM RISCO</span><h2>Decisões que pedem atenção</h2>${data.at_risk?.length ? data.at_risk.map(item => `<div class="list-item"><strong>${esc(item.name)}</strong><div class="muted">${esc(item.risk_label)} · faltam ${minutesLabel(item.remaining_minutes)} · capacidade ${minutesLabel(item.capacity_until_deadline_minutes)}${item.first_feasible_date ? ` · viável em ${esc(item.first_feasible_date)}` : ""}</div></div>`).join("") : empty("Sem risco crítico", "A capacidade atual comporta os itens com prazo configurado.")}</section></section><section class="grid analytics-layout"><section class="card"><span class="tag">PRÓXIMOS PRAZOS E AVALIAÇÕES</span><h2>Acompanhar a seguir</h2>${data.upcoming_evaluations?.map(item => `<div class="list-item"><strong>${esc(item.title)}</strong><div class="muted">${esc(item.subject_name)} · ${esc(item.date)} · ${label(item.status)}${item.score != null ? ` · nota ${item.score}/${item.max_score || "—"}` : ""}</div></div>`).join("") || empty("Sem avaliações próximas", "Avaliações cadastradas nas disciplinas aparecerão aqui.")}</section><section class="card"><span class="tag">CONTEÚDOS</span><h2>Mais estudados e sem atividade</h2><h3>Mais estudados</h3>${data.most_studied_contents?.slice(0, 5).map(item => `<div class="list-item"><strong>${esc(item.name)}</strong><div class="muted">${esc(item.subject_name)} · ${minutesLabel(item.seconds / 60)} · última atividade ${esc(item.last_activity || "—")}</div></div>`).join("") || '<p class="muted">Ainda não há tempo real por conteúdo.</p>'}<h3>Sem atividade recente</h3>${data.inactive_contents?.slice(0, 5).map(item => `<div class="list-item"><strong>${esc(item.name)}</strong><div class="muted">${esc(item.subject_name)} · última atividade ${esc(item.last_session_date || "nunca")}</div></div>`).join("") || '<p class="muted">Nenhum conteúdo pendente sem atividade recente.</p>'}</section></section><section class="card future-subjects"><span class="tag">PRÓXIMAS DISCIPLINAS</span><h2>Futuras, sem demanda de horário</h2><p class="muted">Estas disciplinas estão como Não disponível; aparecem apenas para referência e não participam de risco, demanda ou planejamento.</p>${data.ideal?.future_subjects?.length ? data.ideal.future_subjects.slice(0, 8).map(item => `<span class="future-chip">${esc(item.name)} · ${esc(item.start_date || item.end_date || item.deadline_date || "sem data")}</span>`).join("") : "<p class=\"muted\">Nenhuma disciplina futura cadastrada.</p>"}</section>`;
  app.insertAdjacentHTML("beforeend", `<section class="grid analytics-layout"><section class="card"><span class="tag">PRÓXIMOS ENCERRAMENTOS</span><h2>Prazos por esforço</h2>${data.upcoming_deadlines?.length ? data.upcoming_deadlines.map(item => `<div class="list-item"><strong>${esc(item.name)}</strong><div class="muted">${esc(item.deadline)} · faltam ${minutesLabel(item.remaining_minutes)} · ${esc(item.risk_label)}</div></div>`).join("") : empty("Sem prazos configurados", "Defina prazo e esforço pessoal na disciplina ou no estudo paralelo.")}</section><section class="card"><span class="tag">MÉDIAS E NOTAS</span><h2>Aproveitamento por disciplina</h2>${data.grade_by_subject?.length ? data.grade_by_subject.map(item => `<div class="list-item"><div class="row"><strong>${esc(item.subject_name)}</strong><span>${item.weighted_average_percent == null ? `${item.simple_average_percent}%` : `${item.weighted_average_percent}%`}</span></div><div class="muted">${item.evaluations} avaliação(ões) com nota · média simples ${item.simple_average_percent}%${item.weighted_average_percent == null ? "" : ` · ponderada ${item.weighted_average_percent}%`}</div></div>`).join("") : empty("Sem notas lançadas", "Cadastre avaliações e notas no detalhe da disciplina.")}</section></section>`);
  $("#analytics-filters", app).onsubmit = event => {
    event.preventDefault();
    const values = fields(event.currentTarget);
    analyticsView.range = values.range;
    analyticsView.start = values.start;
    analyticsView.end = values.end;
    analyticsView.formationId = values.formation_id;
    analyticsView.itemId = values.item_id;
    analyticsView.kind = values.kind;
    if (analyticsView.range === "custom" && (!validCalendarDate(values.start) || !validCalendarDate(values.end) || values.end < values.start)) return toast("Informe um intervalo de datas válido.");
    syncAnalyticsLocation(); render();
  };
}

function projectProgress(project) {
  const total = Number(project.task_count || 0);
  const completed = Number(project.completed_tasks || 0);
  return {total, completed, percent: total ? clampPercent(completed / total * 100) : 0};
}

async function renderProjects() {
  const projects = await api("/projects?archived=1");
  const groups = {
    active: projects.filter(project => !project.archived_at && project.status !== "completed"),
    completed: projects.filter(project => !project.archived_at && project.status === "completed"),
    archived: projects.filter(project => Boolean(project.archived_at) || project.status === "archived"),
    all: projects,
  };
  const visible = groups[projectsView.filter] || groups.active;
  const taskTotal = projects.reduce((total, project) => total + Number(project.task_count || 0), 0);
  const taskCompleted = projects.reduce((total, project) => total + Number(project.completed_tasks || 0), 0);
  const filters = [["active", "Ativos"], ["completed", "Concluídos"], ["archived", "Arquivados"], ["all", "Todos"]];
  app.innerHTML = `<section class="projects-shell"><div class="bar"><div><span class="tag">PROJETOS</span><h2>Um espaço separado dos estudos</h2><p class="muted">Tarefas, prazo e progresso de cada projeto sem interferir na sua agenda de estudo.</p></div><button class="button primary" data-new-project>Novo projeto</button></div><div class="grid kpis">${statCard("Projetos ativos", groups.active.length, "em andamento ou pausados", "▣", "violet")}${statCard("Concluídos", groups.completed.length, "mantidos para consulta", "✓", "green")}${statCard("Arquivados", groups.archived.length, "fora da lista principal", "▤", "blue")}${statCard("Tarefas concluídas", `${taskCompleted}/${taskTotal}`, "em todos os projetos", "☑", "amber")}</div><div class="content-tabs" role="group" aria-label="Filtro de projetos">${filters.map(([value,text]) => `<button type="button" data-project-filter="${value}" aria-pressed="${projectsView.filter === value}">${text} <span>${groups[value].length}</span></button>`).join("")}</div><section class="project-grid">${visible.map(project => { const progress = projectProgress(project); return `<article class="card project-card"><div class="project-card-header"><div><span class="tag">${project.archived_at ? "ARQUIVADO" : label(project.status)}</span><h2>${esc(project.name)}</h2><p class="muted">${esc(project.objective || project.description || "Sem objetivo registrado.")}</p></div><button class="button" data-project="${project.id}">Abrir tarefas</button></div><div class="progress" aria-label="${progress.percent}% das tarefas concluídas"><i style="width:${progress.percent}%"></i></div><div class="project-card-meta"><span>${progress.completed}/${progress.total} tarefa(s) concluída(s)</span><span>${project.target_date ? `Prazo ${formatLocalDate(project.target_date, {day:"2-digit", month:"short", year:"numeric"})}` : "Sem prazo"}</span><span>${project.estimated_minutes ? `Estimativa ${minutesLabel(project.estimated_minutes)}` : "Sem estimativa"}</span></div></article>`; }).join("") || empty("Nenhum projeto neste recorte", projectsView.filter === "archived" ? "Não há projetos arquivados." : "Crie um projeto para acompanhar tarefas fora dos estudos.")}</section></section>`;
  app.querySelectorAll("[data-project-filter]").forEach(button => button.addEventListener("click", () => { projectsView.filter = button.dataset.projectFilter; renderProjects(); }));
}

function studyPlanningPayload(values, form) {
  const numberOrNull = key => values[key] === "" || values[key] == null ? null : Number(values[key]);
  return {
    ...values,
    priority:Number(values.priority), difficulty:Number(values.difficulty),
    weekly_goal_minutes:numberOrNull("weekly_goal_minutes"),
    required_study_minutes:numberOrNull("required_study_minutes"),
    minimum_weekly_minutes:numberOrNull("minimum_weekly_minutes"),
    preferred_block_minutes:numberOrNull("preferred_block_minutes"),
    allowed_weekdays:checkedWeekdays(form),
  };
}

function studyPlanningFields(study = {}) {
  const parallel = study.origin !== "curriculum";
  return `<label>Prioridade-base (1–5)<input name="priority" type="number" min="1" max="5" value="${study.priority || 3}" required></label><label>Dificuldade (1–5)<input name="difficulty" type="number" min="1" max="5" value="${study.difficulty || 3}" required></label><label>Objetivo total <span class="field-help">Minutos que você pretende dedicar pessoalmente.</span><input name="required_study_minutes" type="number" min="1" value="${study.required_study_minutes || ""}" placeholder="ex.: 2520 para 42 h"></label><label>Meta semanal <span class="field-help">Minutos por semana; mantém o item planejável mesmo sem objetivo total.</span><input name="weekly_goal_minutes" type="number" min="1" value="${study.weekly_goal_minutes || ""}"></label>${parallel ? `<label>Mínimo semanal garantido <span class="field-help">O planejador reserva esse tempo antes de preencher matérias urgentes.</span><input name="minimum_weekly_minutes" type="number" min="1" value="${study.minimum_weekly_minutes || ""}"></label>` : ""}<label>Prazo<input name="target_date" type="date" value="${study.target_date || ""}"></label><label>Duração preferida do bloco (min)<input name="preferred_block_minutes" type="number" min="1" value="${study.preferred_block_minutes || ""}" placeholder="usa a duração padrão"></label>${weekdaysInputs(study.allowed_weekdays)}`;
}

function newStudy() {
  modal("Novo estudo paralelo", `<label>Nome<input name="personal_name" required></label><p class="muted">Configure esforço total, meta semanal ou ambos. O mínimo semanal é protegido quando houver capacidade; se uma entrega curricular urgente ocupar a janela, a prévia mostrará o que ficou pendente.</p>${studyPlanningFields()}`, async (values, form) => api("/studies", {method:"POST", body:JSON.stringify(studyPlanningPayload(values, form))}));
}

function studyEditor(study) {
  modal(`Editar ${esc(study.name)}`, `${studyPlanningFields(study)}<label>Status<select name="status">${["active", "paused"].map(key => `<option value="${key}" ${key === study.status ? "selected" : ""}>${label(key)}</option>`).join("")}</select></label>`, (values, form) => api(`/studies/${study.id}`, {method:"PATCH", body:JSON.stringify(studyPlanningPayload(values, form))}));
}

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
  if (target.dataset.focusStudy) return openPlanningFocus(null, target, Number(target.dataset.focusStudy), target.dataset.focusTopic ? Number(target.dataset.focusTopic) : null);
  if (target.dataset.addTodaySuggestion !== undefined) {
    await api("/planned", {method:"POST", body:JSON.stringify({
      study_subject_id:Number(target.dataset.suggestStudy),
      topic_id:target.dataset.suggestTopic ? Number(target.dataset.suggestTopic) : null,
      scheduled_date:target.dataset.suggestDate,
      start_time:target.dataset.suggestStart,
      planned_duration_minutes:Number(target.dataset.suggestDuration),
    })});
    toast("Sugestão adicionada à agenda de hoje.");
    return render();
  }
  if (target.dataset.manual !== undefined) return openSession();
  if (target.dataset.startPlan) return openPlanningFocus(Number(target.dataset.startPlan), target);
  if (target.dataset.availability !== undefined) return openAvailability();
  if (target.dataset.editPlanningSettings !== undefined) return openPlanningSettings(await api("/settings"));
  if (target.dataset.newPlan !== undefined) return openPlanEditor();
  if (target.dataset.plan) return openPlanActions(Number(target.dataset.plan), target);
  if (target.dataset.deletePlanningDay) return openPlanningDayDelete(target.dataset.deletePlanningDay, Number(target.dataset.planningDayCount), target);
  if (target.dataset.generate !== undefined) return openPlanGenerationDialog();
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
    if (target.dataset.curriculumAction === "details") return openCurriculumDetail(row.id, target);
    if (target.dataset.curriculumAction === "edit") return curriculumEditor(row.formation_id || formationView.selectedId, row);
    if (target.dataset.curriculumAction === "status") return openCurriculumStatus(row);
    if (target.dataset.curriculumAction === "review") return openCurriculumReview(row);
    if (target.dataset.curriculumAction === "clear-review") return openCurriculumReview(row, "none");
    if (target.dataset.curriculumAction === "archive") return confirmAction({
      title:"Arquivar disciplina",
      message:"A disciplina deixará os estudos atuais. Blocos automáticos futuros serão cancelados; blocos manuais, sessões e histórico serão preservados.",
      confirmLabel:"Arquivar disciplina", opener:target,
      onConfirm:async () => api(`/curriculum/${row.id}/archive`, {method:"POST"}),
    });
    if (target.dataset.curriculumAction === "restore") { await api(`/curriculum/${row.id}/restore`, {method:"POST"}); toast("Disciplina restaurada."); return render(); }
    if (target.dataset.curriculumAction === "dependencies") return openDependencies("curriculum", row.id, row.name, target);
    if (target.dataset.curriculumAction === "destroy") return openTypedDestroy({kind:"curriculum", ident:row.id, name:row.name, endpoint:`/curriculum/${row.id}/destroy`, opener:target, description:"A exclusão definitiva pode incluir estudos, tópicos, blocos, sessões, anotações e revisões vinculados a esta disciplina."});
  }
  if (target.dataset.detailEditCurriculum) {
    const detail = await api(`/curriculum/${target.dataset.detailEditCurriculum}`);
    $("#modal-root").replaceChildren();
    return curriculumEditor(detail.curriculum.formation_id, detail.curriculum);
  }
  if (target.dataset.detailAddContent) { $("#modal-root").replaceChildren(); return contentEditor(Number(target.dataset.detailAddContent)); }
  if (target.dataset.detailEditContent) {
    const data = await api(`/contents/${target.dataset.detailEditContent}/history`);
    $("#modal-root").replaceChildren();
    return contentEditor(data.content.curriculum_subject_id, data.content);
  }
  if (target.dataset.detailArchiveContent) {
    return confirmAction({title:"Arquivar conteúdo", message:"Arquivar este conteúdo? Ele sai das sugestões. Blocos automáticos futuros serão cancelados; blocos manuais e o histórico são preservados.", confirmLabel:"Arquivar conteúdo", opener:target, onConfirm:async () => { await api(`/contents/${target.dataset.detailArchiveContent}/archive`, {method:"POST"}); toast("Conteúdo arquivado."); }});
  }
  if (target.dataset.detailRestoreContent) {
    await api(`/contents/${target.dataset.detailRestoreContent}/restore`, {method:"POST"});
    toast("Conteúdo restaurado.");
    return render();
  }
  if (target.dataset.detailDeleteContent) {
    return confirmAction({title:"Excluir conteúdo", message:`Excluir “${target.dataset.detailContentName}” definitivamente? Se houver sessões, blocos ou avaliações, arquive-o para preservar o histórico.`, confirmLabel:"Excluir conteúdo", opener:target, onConfirm:async () => { await api(`/contents/${target.dataset.detailDeleteContent}`, {method:"DELETE"}); toast("Conteúdo excluído."); }});
  }
  if (target.dataset.detailContentHistory) return openContentHistory(Number(target.dataset.detailContentHistory), target);
  if (target.dataset.detailAddEvaluation) {
    const currentModal = target.closest("form"); const contents = JSON.parse(currentModal?.dataset.curriculumContents || "[]");
    $("#modal-root").replaceChildren(); return evaluationEditor(Number(target.dataset.detailAddEvaluation), contents);
  }
  if (target.dataset.detailEditEvaluation) {
    const currentModal = target.closest("form"); const curriculumId = Number(currentModal?.dataset.curriculumId);
    const detail = await api(`/curriculum/${curriculumId}`); const evaluation = detail.evaluations.evaluations.find(item => item.id === Number(target.dataset.detailEditEvaluation));
    $("#modal-root").replaceChildren(); return evaluationEditor(curriculumId, detail.contents || [], evaluation);
  }
  if (target.dataset.detailDeleteEvaluation) {
    return confirmAction({title:"Excluir avaliação", message:`Excluir “${target.dataset.detailEvaluationName}” definitivamente?`, confirmLabel:"Excluir avaliação", opener:target, onConfirm:async () => { await api(`/evaluations/${target.dataset.detailDeleteEvaluation}`, {method:"DELETE"}); toast("Avaliação excluída."); }});
  }
  if (target.dataset.detailTimeline) { $("#modal-root").replaceChildren(); return openCurriculumTimeline(Number(target.dataset.detailTimeline)); }
  if (target.dataset.addStudy) {
    const created = await api(`/curriculum/${target.dataset.addStudy}/add-study`, {method:"POST", body:JSON.stringify({})});
    const formationId = target.dataset.addStudyFormation;
    toast("Disciplina vinculada aos Estudos atuais. Agora adicione os tópicos que deseja estudar.");
    if (page === "formations" && formationId) {
      window.location.assign(`/studies?study_filter=active&formation_id=${encodeURIComponent(formationId)}&selected=${encodeURIComponent(created.id)}&panel=topics`);
      return;
    }
    studiesView.formationId = formationId || studiesView.formationId;
    studiesView.visibility = "active";
    studiesView.selectedId = created.id;
    studiesView.expandedStudyId = created.id;
    studiesView.panel = "topics";
    syncStudiesLocation();
    return render();
  }
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
  if (target.dataset.planStudy) return openPlanEditor(null, {studyId:Number(target.dataset.planStudy)});
  if (target.dataset.editStudy) {
    const study = studiesView.rows?.find(item => item.id === Number(target.dataset.editStudy)) || (await api("/studies?visibility=all")).find(item => item.id === Number(target.dataset.editStudy));
    return studyEditor(study);
  }
  if (target.dataset.studyPause) { await api(`/studies/${target.dataset.studyPause}/pause`, {method:"POST"}); toast("Estudo pausado."); return render(); }
  if (target.dataset.studyResume) { await api(`/studies/${target.dataset.studyResume}/resume`, {method:"POST"}); toast("Estudo retomado."); return render(); }
  if (target.dataset.studyArchive) return confirmAction({
    title:"Arquivar estudo",
    message:"O estudo deixará a lista atual. Blocos automáticos futuros serão cancelados; blocos manuais, sessões e histórico serão preservados.",
    confirmLabel:"Arquivar estudo", opener:target,
    onConfirm:async () => api(`/studies/${target.dataset.studyArchive}/archive`, {method:"POST"}),
  });
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
      return openPlanningFocus(null, target, study.id);
    }
  }
  if (target.dataset.newProject !== undefined) return projectEditor();
  if (target.dataset.project) return openProject(Number(target.dataset.project));
  if (target.dataset.editProject) { $("#modal-root").replaceChildren(); return projectEditor(await api(`/projects/${target.dataset.editProject}`)); }
  if (target.dataset.addTask) return modal("Nova tarefa", `<label>Nome<input name="name" required></label>`, values => api(`/projects/${target.dataset.addTask}/tasks`,{method:"POST",body:JSON.stringify(values)}));
  if (target.dataset.toggleTask) { await api(`/project-tasks/${target.dataset.toggleTask}`,{method:"PATCH",body:JSON.stringify({status:target.dataset.taskStatus==="completed"?"pending":"completed"})}); return openProject(Number(target.closest(".modal")?.querySelector("[data-edit-project]")?.dataset.editProject)); }
  if (target.dataset.deleteTask) { await api(`/project-tasks/${target.dataset.deleteTask}`,{method:"DELETE"}); $("#modal-root").replaceChildren(); toast("Tarefa excluída."); return render(); }
  if (target.dataset.studyDetail) {
    const studyId = Number(target.dataset.studyDetail);
    studiesView.selectedId = studyId;
    studiesView.expandedStudyId = studyId;
    studiesView.panel = "topics";
    syncStudiesLocation();
    return renderStudyTopics(studyId);
  }
  if (target.dataset.curriculumTopicDistribution) return openCurriculumTopicDistribution(Number(target.dataset.curriculumTopicDistribution), target, target.dataset.topicDistributionMode || "proportional");
  if (target.dataset.topicDistribution) return openTopicDistribution(Number(target.dataset.topicDistribution), target, target.dataset.topicDistributionMode || "proportional");
  if (target.dataset.curriculumTopicMove) return moveCurriculumTopic(Number(target.dataset.topicCurriculum), Number(target.dataset.topicId), target.dataset.curriculumTopicMove);
  if (target.dataset.topicMove) return moveStudyTopic(Number(target.dataset.topicStudy), Number(target.dataset.topicId), target.dataset.topicMove);
  if (target.dataset.newTopic) return studyTopicEditor(Number(target.dataset.newTopic));
  if (target.dataset.editStudyTopic) {
    const detail = await api(`/studies/${target.dataset.topicStudy}`);
    const topic = [...(detail.groups || []).flatMap(group => group.topics || []), ...(detail.ungrouped_topics || [])].find(item => Number(item.id) === Number(target.dataset.editStudyTopic));
    if (!topic) throw new Error("Não foi possível localizar este tópico.");
    return studyTopicEditor(Number(target.dataset.topicStudy), topic);
  }
  if (target.dataset.completeStudyTopic) {
    return completeStudyTopic(Number(target.dataset.completeStudyTopic), Number(target.dataset.topicStudy));
  }
  if (target.dataset.archiveStudyTopic) {
    return confirmAction({
      title:"Arquivar tópico",
      message:"O tópico sai de novas sugestões. Blocos automáticos futuros serão cancelados; blocos manuais e o histórico serão preservados.",
      confirmLabel:"Arquivar tópico", opener:target,
      onConfirm:async () => api(`/topics/${target.dataset.archiveStudyTopic}/archive`, {method:"POST"}),
    });
  }
  if (target.dataset.planStudyTopic) return openPlanEditor(null, {studyId:Number(target.dataset.planStudyTopic), topicId:Number(target.dataset.topicId)});
  if (target.dataset.review) { const review = (await api("/reviews")).find(item => item.id === Number(target.dataset.review)); return openSession({review:{...review,rating:target.dataset.rating}}); }
  if (target.dataset.deleteSession) { await api(`/sessions/${target.dataset.deleteSession}`,{method:"DELETE"}); toast("Sessão excluída e domínio reconciliado."); return render(); }
  if (target.dataset.export !== undefined) { const rows = await api("/sessions"); const header = ["data","matéria","tópico","tipo","duração_segundos","início","fim","domínio_antes","domínio_depois","observação"]; const csv = [header,...rows.map(row=>[row.date,row.subject_name,row.topic_name,row.entry_method,row.duration_seconds,row.started_at,row.ended_at,row.mastery_before,row.mastery_after,row.notes])].map(row=>row.map(value=>`"${String(value??"").replaceAll('"','""')}"`).join(",")).join("\n"); const link = document.createElement("a"); link.href=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"})); link.download="historico-plano.csv"; link.click(); URL.revokeObjectURL(link.href); return; }
} catch (error) { toast(error.message); } });

async function render() {
  app.setAttribute("aria-busy", "true");
  try {
    document.querySelectorAll("[data-nav]").forEach(link => {
      const active = link.dataset.nav === page;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
    });
    $("#date-label").textContent = formatLocalDate(new Date(), {weekday:"long", day:"numeric", month:"long", year:"numeric"});
    const pages = {today:renderToday,planning:renderPlanning,formations:renderFormations,studies:renderStudies,reviews:renderReviews,history:renderHistory,analytics:renderAnalytics,projects:renderProjects};
    await (pages[page] || renderToday)();
  } catch (error) {
    app.innerHTML = empty("Não foi possível carregar esta página", esc(error.message));
  } finally {
    app.setAttribute("aria-busy", "false");
  }
}

installResponsiveNavigation();
let externalRefreshTimer = null;
let externalRefreshPending = false;

function focusedEditableControl() {
  const active = document.activeElement;
  return active instanceof HTMLElement && active.matches("input, textarea, select");
}

function flushRemoteRefresh() {
  if (!externalRefreshPending || document.hidden || focusedEditableControl()) return;
  window.clearTimeout(externalRefreshTimer);
  externalRefreshTimer = window.setTimeout(() => {
    // A field may have regained focus while the debounce was waiting. Keep the
    // change pending instead of rebuilding the screen and losing the draft.
    if (document.hidden || focusedEditableControl()) return;
    externalRefreshPending = false;
    render();
  }, 180);
}

function refreshAfterRemoteChange() {
  // A alteração é mantida até ser seguro redesenhar. Assim, uma mudança vinda
  // de outra aba não desaparece só porque a pessoa está digitando aqui.
  externalRefreshPending = true;
  flushRemoteRefresh();
}
window.addEventListener("plano:data-changed", refreshAfterRemoteChange);
document.addEventListener("blur", event => {
  if (!externalRefreshPending || !(event.target instanceof HTMLElement) || !event.target.matches("input, textarea, select")) return;
  // O próximo foco ainda não foi atualizado durante o blur; aguarda um ciclo
  // para não trocar a tela caso a pessoa apenas navegue para outro campo.
  window.setTimeout(flushRemoteRefresh, 0);
}, true);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) flushRemoteRefresh();
});
render();
