import {api} from "./api.js";

const app = document.querySelector("#focus-app");
const dialogRoot = document.querySelector("#focus-dialog-root");
const toastRoot = document.querySelector("#focus-toast-root");
const query = new URLSearchParams(window.location.search);
const DEFAULT_DURATION_MINUTES = 50;
const DATA_CHANGED_EVENT = "plano:data-changed";

const queryId = (...keys) => {
  for (const key of keys) {
    const value = query.get(key);
    if (/^\d+$/.test(value || "")) return Number(value);
  }
  return null;
};

const plannedId = queryId("planned_id");
const requestedStudyId = queryId("study_id", "study_subject_id");
const requestedTopicId = queryId("topic_id");
const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[char]));

let studies = [];
let topics = [];
let clock = null;
let polling = null;
let refreshDebounce = null;
let noteSaveTimer = null;
let noteSavePromise = null;
let noteSaving = false;
let noteRevision = 0;
let finalizing = false;

const state = {
  mode: "loading",
  focus: null,
  activeConflict: null,
  planned: null,
  studyId: requestedStudyId,
  topicId: requestedTopicId,
  plannedDurationMinutes: DEFAULT_DURATION_MINUTES,
  receivedAt: 0,
  receivedElapsedSeconds: 0,
  note: {id: null, title: "", tags: "", content: ""},
  noteDirty: false,
  noteView: "editor",
  noteStatus: "saved",
  noteError: "",
  completedResult: null,
};

function seconds(value) {
  return Math.max(0, Math.floor(Number(value || 0)));
}

function formatDuration(value) {
  const total = seconds(value);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  return [hours, minutes, remainder]
    .map((item, index) => index === 0 && !hours ? null : String(item).padStart(2, "0"))
    .filter(item => item !== null)
    .join(":");
}

function durationLabel(value) {
  const total = seconds(value);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  return hours ? `${hours} h${minutes ? ` ${minutes} min` : ""}` : `${minutes} min`;
}

function minutesLabel(value) {
  return `${Math.max(1, Math.round(Number(value || 0)))} min`;
}

function toast(message) {
  const element = document.createElement("div");
  element.className = "focus-toast";
  element.textContent = message;
  toastRoot.replaceChildren(element);
  window.setTimeout(() => element.remove(), 4200);
}

function isActive(focus = state.focus) {
  return Boolean(focus?.is_active || ["running", "paused", "recovery_required"].includes(focus?.status));
}

function selectedStudy() {
  return studies.find(item => item.id === Number(state.studyId));
}

function activeMatchesRequest(active) {
  if (!active) return false;
  if (plannedId) return Number(active.planned_session_id) === plannedId;
  if (requestedStudyId && Number(active.study_subject_id) !== requestedStudyId) return false;
  if (requestedTopicId && Number(active.topic_id) !== requestedTopicId) return false;
  return true;
}

function resetNote() {
  state.note = {id: null, title: "", tags: "", content: ""};
  state.noteDirty = false;
  noteRevision = 0;
}

function applyFocus(snapshot) {
  if (!snapshot) return;
  const changedId = Number(state.focus?.id || 0) !== Number(snapshot.id || 0);
  state.focus = snapshot;
  state.receivedAt = Date.now();
  state.receivedElapsedSeconds = seconds(snapshot.elapsed_seconds);
  state.studyId = Number(snapshot.study_subject_id || state.studyId || 0) || null;
  state.topicId = snapshot.topic_id ? Number(snapshot.topic_id) : null;
  if (changedId) resetNote();
  if (!state.noteDirty) state.note.id = snapshot.note_id || null;
  state.mode = snapshot.status === "completed" ? "completed" : snapshot.status === "cancelled" ? "cancelled" : "active";
}

function elapsedSeconds() {
  if (!state.focus) return 0;
  const base = state.receivedElapsedSeconds;
  return state.focus.status === "running"
    ? base + Math.max(0, Math.floor((Date.now() - state.receivedAt) / 1000))
    : base;
}

function plannedDurationMinutes() {
  return Math.max(1, Number(
    state.focus?.planned_duration_minutes ||
    state.planned?.planned_duration_minutes ||
    state.plannedDurationMinutes ||
    DEFAULT_DURATION_MINUTES,
  ));
}

function noteIsMeaningful() {
  return Boolean(state.note.id || state.note.title.trim() || state.note.tags.trim() || state.note.content.trim());
}

function notePayload() {
  return {
    title: state.note.title.trim(),
    tags: state.note.tags,
    content_markdown: state.note.content,
  };
}

function applyNote(note) {
  if (!note) return;
  state.note = {
    id: note.id || state.note.id,
    title: note.title ?? state.note.title,
    tags: Array.isArray(note.tags) ? note.tags.join(", ") : (note.tags ?? state.note.tags),
    content: note.content_markdown ?? note.content ?? state.note.content,
  };
}

function noteStatusText() {
  return state.noteStatus === "saving" ? "Salvando…" : state.noteStatus === "error" ? "Erro ao salvar" : "Salvo";
}

function updateNoteStatus() {
  const label = app.querySelector("[data-note-status]");
  if (!label) return;
  label.className = `note-status ${state.noteStatus}`;
  label.textContent = noteStatusText();
  label.title = state.noteError || "";
}

function markdown(value) {
  return esc(value).replaceAll("\n", "<br>");
}

async function topicsFor(studyId) {
  if (!studyId) return [];
  const detail = await api(`/studies/${studyId}`);
  return [...detail.groups.flatMap(group => group.topics), ...detail.ungrouped_topics];
}

function studyOptions() {
  return studies.map(study => `<option value="${study.id}" ${study.id === Number(state.studyId) ? "selected" : ""}>${esc(study.name)}</option>`).join("");
}

function topicOptions() {
  return `<option value="">Sem tópico</option>${topics.map(topic => `<option value="${topic.id}" ${topic.id === Number(state.topicId) ? "selected" : ""}>${esc(topic.name)}${topic.status ? ` · ${esc(topic.status)}` : ""}</option>`).join("")}`;
}

function renderLoading() {
  stopClock();
  app.innerHTML = '<section class="focus-card focus-loading"><span class="tag">PREPARANDO</span><h1>Organizando sua sessão…</h1><p class="muted">Consultando a sessão persistente e seu rascunho de anotações.</p></section>';
}

function renderError(error) {
  stopClock();
  app.innerHTML = `<section class="focus-card focus-error"><span class="tag">NÃO FOI POSSÍVEL ABRIR</span><h1>Não foi possível preparar a sessão.</h1><p class="muted">${esc(error.message)}</p><div class="focus-form-actions"><a class="button" href="/">Voltar ao plano</a><button class="button primary" type="button" data-retry>Tentar novamente</button></div></section>`;
  app.querySelector("[data-retry]")?.addEventListener("click", initialize);
}

function renderSetup() {
  stopClock();
  if (!studies.length) {
    app.innerHTML = '<section class="focus-setup focus-card"><span class="tag">SESSÃO LIVRE</span><h1>Não há matérias disponíveis</h1><p class="muted">Crie ou adicione um estudo antes de iniciar uma sessão livre.</p><div class="focus-form-actions"><a class="button primary" href="/studies">Abrir estudos</a><a class="button ghost" href="/">Voltar ao plano</a></div></section>';
    return;
  }
  app.innerHTML = `<section class="focus-setup focus-card"><span class="tag">SESSÃO LIVRE</span><h1>Em que você quer focar?</h1><p class="muted">A sessão será salva no plano ao iniciar. Fechar esta aba não a encerra.</p><form id="focus-setup-form" class="focus-form"><label>Matéria<select id="focus-study" name="study_subject_id" required>${studyOptions()}</select></label><label>Tópico<select id="focus-topic" name="topic_id">${topicOptions()}</select></label><label>Duração planejada (minutos)<input name="planned_duration" type="number" min="1" max="1440" value="${Math.max(1, Math.round(state.plannedDurationMinutes))}" required></label><div class="focus-form-actions"><a class="button ghost" href="/">Voltar ao plano</a><button class="button primary" type="submit">Preparar sessão</button></div></form></section>`;
  const form = app.querySelector("#focus-setup-form");
  form?.querySelector("#focus-study")?.addEventListener("change", async event => {
    state.studyId = Number(event.target.value);
    state.topicId = null;
    try {
      topics = await topicsFor(state.studyId);
      renderSetup();
    } catch (error) {
      toast(error.message);
    }
  });
  form?.addEventListener("submit", event => {
    event.preventDefault();
    const values = new FormData(form);
    const duration = Number(values.get("planned_duration"));
    if (!Number.isFinite(duration) || duration < 1) return toast("Informe uma duração de pelo menos um minuto.");
    state.studyId = Number(values.get("study_subject_id"));
    state.topicId = values.get("topic_id") ? Number(values.get("topic_id")) : null;
    state.plannedDurationMinutes = Math.round(duration);
    state.mode = "ready";
    renderFocus();
  });
}

function renderReady() {
  stopClock();
  const subject = state.planned?.subject_name || selectedStudy()?.name || "Matéria";
  const topic = state.planned?.topic_name || topics.find(item => item.id === Number(state.topicId))?.name || "Sem tópico definido";
  const duration = plannedDurationMinutes();
  app.innerHTML = `<section class="focus-setup focus-card"><span class="tag">${state.planned ? "BLOCO PLANEJADO" : "SESSÃO LIVRE"}</span><h1>${esc(subject)}</h1><p class="focus-topic">${esc(topic)}</p><div class="focus-timer-details"><div><span>Duração planejada</span><strong>${minutesLabel(duration)}</strong></div><div><span>Estado</span><strong>Pronta para começar</strong></div><div><span>Persistência</span><strong>Salva no plano</strong></div></div><p class="muted">O cronômetro será controlado pelo servidor e poderá ser retomado em outra aba.</p><div class="focus-form-actions">${state.planned ? '<a class="button ghost" href="/">Voltar ao plano</a>' : '<button class="button ghost" type="button" data-back>Editar escolha</button>'}<button class="button primary" type="button" data-start>Iniciar foco</button></div></section>`;
  app.querySelector("[data-back]")?.addEventListener("click", () => {
    state.mode = "setup";
    renderFocus();
  });
  app.querySelector("[data-start]")?.addEventListener("click", startFocus);
}

function renderConflict() {
  stopClock();
  const active = state.activeConflict;
  const activeTopic = active?.topic_name ? ` — ${active.topic_name}` : "";
  const requested = state.planned?.subject_name || selectedStudy()?.name || "esta nova sessão";
  app.innerHTML = `<section class="focus-setup focus-card"><span class="tag warning">SESSÃO EM ANDAMENTO</span><h1>Já existe uma sessão ativa</h1><p class="muted"><strong>${esc(active?.subject_name || "Matéria")}</strong>${esc(activeTopic)} está ${active?.status === "paused" ? "pausada" : "em foco"}. Só uma sessão pode ficar ativa por vez.</p><p class="muted">Você tentou abrir: <strong>${esc(requested)}</strong>.</p><div class="focus-form-actions"><button class="button primary" type="button" data-open-active>Voltar à sessão ativa</button><button class="button" type="button" data-replace-active>Encerrar atual e iniciar esta</button><a class="button ghost" href="/">Cancelar</a></div></section>`;
  app.querySelector("[data-open-active]")?.addEventListener("click", openActive);
  app.querySelector("[data-replace-active]")?.addEventListener("click", confirmReplaceActive);
}

function renderRecovery() {
  stopClock();
  const elapsed = elapsedSeconds();
  app.innerHTML = `<section class="focus-setup focus-card"><span class="tag warning">CONFIRMAÇÃO NECESSÁRIA</span><h1>Sessão muito longa</h1><p class="muted">Esta sessão permaneceu ativa por ${durationLabel(elapsed)}. Confirme o tempo real antes de continuar ou encerrar.</p><form id="focus-recovery-form" class="focus-form"><fieldset><legend>Como tratar o período?</legend><label><input type="radio" name="choice" value="full"> Usei todo o período</label><label><input type="radio" name="choice" value="planned" checked> Encerrar no tempo planejado</label><label><input type="radio" name="choice" value="actual"> Informar duração real</label><label><input type="radio" name="choice" value="discard_excess"> Descartar o trecho excedente</label></fieldset><label data-actual-duration hidden>Duração real (minutos)<input name="actual_minutes" type="number" min="0" max="${Math.floor(elapsed / 60)}" value="${Math.max(1, Math.min(plannedDurationMinutes(), Math.floor(elapsed / 60))) }"></label><label><input type="checkbox" name="resume" value="true"> Retomar depois de confirmar</label><div class="focus-form-actions"><button class="button primary" type="submit">Confirmar período</button><button class="button danger" type="button" data-cancel>Cancelar sessão</button></div></form></section>`;
  const form = app.querySelector("#focus-recovery-form");
  const actual = form?.querySelector("[data-actual-duration]");
  const updateActual = () => {
    actual.hidden = new FormData(form).get("choice") !== "actual";
  };
  form?.querySelectorAll("[name=choice]").forEach(item => item.addEventListener("change", updateActual));
  form?.addEventListener("submit", async event => {
    event.preventDefault();
    const values = new FormData(form);
    const choice = values.get("choice");
    const payload = {version: state.focus.version, choice, resume: values.get("resume") === "true"};
    if (choice === "actual") {
      const duration = Number(values.get("actual_minutes"));
      if (!Number.isFinite(duration) || duration < 0) return toast("Informe uma duração real válida.");
      payload.duration_seconds = Math.round(duration * 60);
    }
    try {
      const snapshot = await api(`/focus/sessions/${state.focus.id}/recover`, {method: "POST", body: JSON.stringify(payload)});
      await useFocus(snapshot);
    } catch (error) {
      await handleFocusError(error);
    }
  });
  app.querySelector("[data-cancel]")?.addEventListener("click", confirmCancel);
}

function topicEffortMessage(result) {
  const effort = result?.topic_effort_result;
  if (result?.topic_effort_alert) return result.topic_effort_alert;
  if (!effort) return "";
  const economy = Math.max(0, Number(effort.economy_minutes || 0));
  const overrun = Math.max(0, Number(effort.overrun_minutes || 0));
  const remaining = Math.max(0, Number(effort.remaining_minutes || 0));
  if (economy) return `Você terminou este tópico ${durationLabel(economy * 60)} antes da estimativa. Essa folga continua sendo sua escolha.`;
  if (overrun) {
    return effort.status === "completed"
      ? `Este tópico consumiu ${durationLabel(overrun * 60)} além da estimativa. O tempo real foi preservado.`
      : `Este tópico consumiu ${durationLabel(overrun * 60)} além da estimativa. Ele continua em andamento e o ritmo foi recalculado sem alterar a estimativa automaticamente.`;
  }
  if (effort.status !== "completed" && remaining) return `Ainda restam cerca de ${durationLabel(remaining * 60)} estimados para este tópico.`;
  return "";
}

function renderCompleted() {
  stopClock();
  const result = state.completedResult || {};
  const next = result.next_topic;
  const nextUrl = next ? `/focus?study_id=${encodeURIComponent(state.focus?.study_subject_id || state.studyId)}&topic_id=${encodeURIComponent(next.id)}` : "";
  const effortMessage = topicEffortMessage(result);
  app.innerHTML = `<section class="focus-complete focus-card"><span class="tag">SESSÃO FINALIZADA</span><h1>Bom trabalho.</h1><p class="muted">Foram registrados ${formatDuration(state.focus?.elapsed_seconds || 0)} de foco real. Histórico, progresso e revisões foram atualizados.</p>${effortMessage ? `<p class="muted">${esc(effortMessage)}</p>` : ""}${result.future_blocks?.automatic_changed ? `<p class="muted">${result.future_blocks.automatic_changed} bloco(s) automático(s) futuro(s) foram tratados; blocos manuais foram preservados.</p>` : ""}${next ? `<p class="muted">Próximo tópico elegível: <strong>${esc(next.name)}</strong>.</p>` : ""}<div class="focus-form-actions">${next ? `<a class="button primary" href="${nextUrl}">Preparar próximo tópico</a>` : ""}<a class="button" href="/history">Ver histórico</a><a class="button ghost" href="/focus">Nova sessão livre</a><a class="button ghost" href="/">Voltar ao plano</a></div></section>`;
}

function renderCancelled() {
  stopClock();
  app.innerHTML = '<section class="focus-complete focus-card"><span class="tag">SESSÃO CANCELADA</span><h1>Sessão cancelada.</h1><p class="muted">Nenhum tempo foi registrado no histórico. Se havia uma anotação, ela foi preservada como rascunho.</p><div class="focus-form-actions"><a class="button primary" href="/focus">Nova sessão livre</a><a class="button ghost" href="/">Voltar ao plano</a></div></section>';
}

function renderActive() {
  const focus = state.focus;
  const elapsed = elapsedSeconds();
  const duration = plannedDurationMinutes();
  const remaining = Math.max(0, duration * 60 - elapsed);
  const running = focus.status === "running";
  const canFinish = (running || focus.status === "paused") && elapsed >= 1 && !finalizing;
  const primary = running
    ? '<button class="button" type="button" data-pause>Pausar</button>'
    : '<button class="button primary" type="button" data-resume>Continuar</button>';
  app.innerHTML = `<div class="focus-grid"><section class="focus-card focus-timer-card"><div class="focus-session-meta"><span class="tag">${focus.planned_session_id ? "BLOCO PLANEJADO" : "SESSÃO LIVRE"}</span><span class="focus-phase">${running ? "Em foco" : "Pausada"}</span></div><h1>${esc(focus.subject_name || "Matéria")}</h1><p class="focus-topic">${esc(focus.topic_name || "Sem tópico definido")}</p><div class="focus-timer" aria-label="Tempo decorrido" data-focus-elapsed>${formatDuration(elapsed)}</div><div class="focus-timer-details"><div><span>Tempo decorrido</span><strong data-focus-elapsed-small>${formatDuration(elapsed)}</strong></div><div><span>Tempo restante</span><strong data-focus-remaining>${formatDuration(remaining)}</strong></div><div><span>Planejado</span><strong>${minutesLabel(duration)}</strong></div></div><p class="focus-overtime ${remaining === 0 && elapsed ? "visible" : ""}" data-focus-overtime>${remaining === 0 && elapsed ? "Você concluiu o tempo planejado. Pode encerrar quando quiser." : ""}</p><div class="focus-controls">${primary}<button class="button" type="button" data-finish ${canFinish ? "" : "disabled"}>${finalizing ? "Finalizando…" : "Encerrar por hoje"}</button><button class="button danger" type="button" data-cancel ${finalizing ? "disabled" : ""}>Cancelar</button></div></section><aside class="focus-card focus-notes-card"><div class="focus-notes-heading"><div><span class="tag">ANOTAÇÕES</span><h2>Seu caderno da sessão</h2></div><span class="note-status ${state.noteStatus}" data-note-status title="${esc(state.noteError)}">${noteStatusText()}</span></div><div class="focus-note-tabs" role="tablist" aria-label="Anotações"><button class="note-tab ${state.noteView === "editor" ? "active" : ""}" type="button" data-note-view="editor" role="tab" aria-selected="${state.noteView === "editor"}">Escrever</button><button class="note-tab ${state.noteView === "preview" ? "active" : ""}" type="button" data-note-view="preview" role="tab" aria-selected="${state.noteView === "preview"}">Prévia</button><button class="button ghost focus-save-note" type="button" data-save-note>Salvar agora</button></div>${state.noteView === "preview" ? `<article class="markdown-preview" aria-label="Prévia segura do Markdown">${markdown(state.note.content)}</article>` : `<div class="focus-note-editor"><label>Título<input id="note-title" value="${esc(state.note.title)}" placeholder="Ex.: Ideias-chave da sessão"></label><label>Tags<input id="note-tags" value="${esc(state.note.tags)}" placeholder="ex.: estudos, revisão"></label><label class="focus-note-content">Markdown<textarea id="note-content" placeholder="Escreva suas anotações em Markdown…">${esc(state.note.content)}</textarea></label></div>`}</aside></div>`;
  bindActiveActions();
  updateClock();
  syncClock();
}

function renderFocus() {
  if (state.mode === "loading") return renderLoading();
  if (state.mode === "setup") return renderSetup();
  if (state.mode === "ready") return renderReady();
  if (state.mode === "conflict") return renderConflict();
  if (state.mode === "completed") return renderCompleted();
  if (state.mode === "cancelled") return renderCancelled();
  if (state.focus?.status === "recovery_required") return renderRecovery();
  if (isActive()) return renderActive();
  return renderSetup();
}

function updateClock() {
  if (!state.focus) return;
  const elapsed = elapsedSeconds();
  const remaining = Math.max(0, plannedDurationMinutes() * 60 - elapsed);
  app.querySelectorAll("[data-focus-elapsed]").forEach(element => { element.textContent = formatDuration(elapsed); });
  app.querySelectorAll("[data-focus-elapsed-small]").forEach(element => { element.textContent = formatDuration(elapsed); });
  app.querySelectorAll("[data-focus-remaining]").forEach(element => { element.textContent = formatDuration(remaining); });
  const overtime = app.querySelector("[data-focus-overtime]");
  if (overtime) {
    overtime.classList.toggle("visible", remaining === 0 && elapsed > 0);
    overtime.textContent = remaining === 0 && elapsed ? "Você concluiu o tempo planejado. Pode encerrar quando quiser." : "";
  }
}

function startClock() {
  if (clock || state.focus?.status !== "running") return;
  clock = window.setInterval(updateClock, 250);
}

function stopClock() {
  if (clock) window.clearInterval(clock);
  clock = null;
}

function syncClock() {
  if (state.focus?.status === "running") startClock();
  else stopClock();
}

function syncPolling() {
  if (polling) window.clearInterval(polling);
  polling = null;
  if (!isActive()) return;
  polling = window.setInterval(() => refreshFromServer(true).catch(() => {}), 30000);
}

function bindActiveActions() {
  app.querySelector("[data-pause]")?.addEventListener("click", pauseFocus);
  app.querySelector("[data-resume]")?.addEventListener("click", resumeFocus);
  app.querySelector("[data-finish]")?.addEventListener("click", openFinishDialog);
  app.querySelector("[data-cancel]")?.addEventListener("click", confirmCancel);
  app.querySelector("[data-save-note]")?.addEventListener("click", async () => {
    try {
      await saveNote();
      toast("Anotação salva.");
    } catch (error) {
      toast(error.message);
    }
  });
  app.querySelectorAll("[data-note-view]").forEach(button => button.addEventListener("click", () => {
    state.noteView = button.dataset.noteView;
    renderFocus();
  }));
  [["#note-title", "title"], ["#note-tags", "tags"], ["#note-content", "content"]].forEach(([selector, field]) => {
    app.querySelector(selector)?.addEventListener("input", event => {
      state.note[field] = event.target.value;
      markNoteDirty();
    });
  });
}

function markNoteDirty() {
  noteRevision += 1;
  state.noteDirty = true;
  state.noteStatus = "saving";
  state.noteError = "";
  updateNoteStatus();
  window.clearTimeout(noteSaveTimer);
  noteSaveTimer = window.setTimeout(() => saveNote().catch(() => {}), 800);
}

async function saveNote() {
  window.clearTimeout(noteSaveTimer);
  const focus = state.focus;
  if (!isActive(focus)) return null;
  if (!noteIsMeaningful()) {
    state.noteDirty = false;
    state.noteStatus = "saved";
    state.noteError = "";
    updateNoteStatus();
    return null;
  }
  if (noteSaving) return noteSavePromise;
  const revision = noteRevision;
  noteSaving = true;
  state.noteStatus = "saving";
  state.noteError = "";
  updateNoteStatus();
  noteSavePromise = (async () => {
    try {
      const result = await api(`/focus/sessions/${focus.id}/note`, {method: "PUT", body: JSON.stringify(notePayload())});
      applyNote(result.note);
      if (result.session) applyFocus(result.session);
      state.noteDirty = noteRevision !== revision;
      state.noteStatus = "saved";
      state.noteError = "";
      updateNoteStatus();
      if (state.noteDirty) window.setTimeout(() => saveNote().catch(() => {}), 0);
      return result.note;
    } catch (error) {
      state.noteStatus = "error";
      state.noteError = error.message;
      updateNoteStatus();
      throw error;
    } finally {
      noteSaving = false;
      noteSavePromise = null;
    }
  })();
  return noteSavePromise;
}

async function hydrateNote() {
  const noteId = state.focus?.note_id;
  if (!noteId || state.noteDirty) return;
  try {
    applyNote(await api(`/notes/${noteId}`));
    state.noteStatus = "saved";
    state.noteError = "";
  } catch (_) {
    // A sessão oficial continua disponível e a nota pode ser buscada novamente.
  }
}

async function useFocus(snapshot, {loadNote = true, render = true} = {}) {
  applyFocus(snapshot);
  if (loadNote) await hydrateNote();
  if (render) renderFocus();
  syncPolling();
}

async function startFocus() {
  const payload = plannedId
    ? {planned_session_id: plannedId}
    : {study_subject_id: state.studyId, topic_id: state.topicId || null, planned_duration_minutes: state.plannedDurationMinutes};
  try {
    const result = await api("/focus/sessions", {method: "POST", body: JSON.stringify(payload)});
    state.activeConflict = null;
    await useFocus(result.session);
    if (result.recovered) toast("Sessão em andamento recuperada.");
  } catch (error) {
    if (error.code === "focus_session_already_active") return loadActiveConflict();
    await handleFocusError(error);
  }
}

async function pauseFocus() {
  try {
    const snapshot = await api(`/focus/sessions/${state.focus.id}/pause`, {method: "POST", body: JSON.stringify({version: state.focus.version})});
    await useFocus(snapshot);
  } catch (error) {
    await handleFocusError(error);
  }
}

async function resumeFocus() {
  try {
    const snapshot = await api(`/focus/sessions/${state.focus.id}/resume`, {method: "POST", body: JSON.stringify({version: state.focus.version})});
    await useFocus(snapshot);
  } catch (error) {
    await handleFocusError(error);
  }
}

function showDialog({title, message, actions}) {
  const previous = document.activeElement;
  dialogRoot.innerHTML = `<div class="focus-dialog-backdrop"><section class="focus-dialog" role="dialog" aria-modal="true"><h2>${esc(title)}</h2><p>${esc(message)}</p><p class="form-error" data-dialog-error></p><div class="focus-dialog-actions">${actions.map((action, index) => `<button class="button ${action.className || ""}" type="button" data-dialog-action="${index}">${esc(action.label)}</button>`).join("")}</div></section></div>`;
  const backdrop = dialogRoot.firstElementChild;
  const close = () => {
    dialogRoot.replaceChildren();
    document.removeEventListener("keydown", onKeydown);
    previous?.focus?.();
  };
  const onKeydown = event => {
    if (event.key === "Escape" && !backdrop.dataset.busy) close();
  };
  document.addEventListener("keydown", onKeydown);
  backdrop.addEventListener("click", event => {
    if (event.target === backdrop && !backdrop.dataset.busy) close();
  });
  backdrop.querySelectorAll("[data-dialog-action]").forEach(button => button.addEventListener("click", async () => {
    const action = actions[Number(button.dataset.dialogAction)];
    if (!action.run) return close();
    backdrop.dataset.busy = "true";
    backdrop.querySelectorAll("button").forEach(item => { item.disabled = true; });
    try {
      await action.run();
      close();
    } catch (error) {
      backdrop.querySelector("[data-dialog-error]").textContent = error.message;
      backdrop.querySelectorAll("button").forEach(item => { item.disabled = false; });
      delete backdrop.dataset.busy;
    }
  }));
  window.setTimeout(() => backdrop.querySelector("button")?.focus(), 0);
}

function confirmCancel() {
  if (!isActive() || finalizing) return;
  showDialog({
    title: "Cancelar sessão?",
    message: noteIsMeaningful() ? "O tempo não entrará no histórico. Sua anotação será preservada como rascunho." : "O tempo desta sessão não entrará no histórico.",
    actions: [
      {label: "Continuar sessão"},
      {
        label: "Cancelar sessão",
        className: "danger",
        run: async () => {
          if (noteIsMeaningful()) await saveNote();
          const snapshot = await api(`/focus/sessions/${state.focus.id}/cancel`, {method: "POST", body: JSON.stringify({version: state.focus.version})});
          await useFocus(snapshot, {loadNote: false});
        },
      },
    ],
  });
}

function confirmReplaceActive() {
  const active = state.activeConflict;
  if (!active) return;
  showDialog({
    title: "Encerrar sessão atual?",
    message: "A sessão em andamento será cancelada sem registrar seu tempo. Depois, esta nova sessão será iniciada.",
    actions: [
      {label: "Voltar"},
      {
        label: "Encerrar e iniciar",
        className: "danger",
        run: async () => {
          await api(`/focus/sessions/${active.id}/cancel`, {method: "POST", body: JSON.stringify({version: active.version})});
          state.activeConflict = null;
          await startFocus();
        },
      },
    ],
  });
}

async function openActive() {
  if (!state.activeConflict) return;
  try {
    const snapshot = await api(`/focus/sessions/${state.activeConflict.id}`);
    state.activeConflict = null;
    await useFocus(snapshot);
  } catch (error) {
    await handleFocusError(error);
  }
}

async function finishFocus(payload) {
  if (!state.focus?.id) throw new Error("A sessão não está mais disponível.");
  if (noteSavePromise) await noteSavePromise;
  const result = await api(`/focus/sessions/${state.focus.id}/finish`, {method: "POST", body: JSON.stringify(payload)});
  if (result.note) applyNote(result.note);
  state.completedResult = result;
  await useFocus(result.session, {loadNote: false});
  return result;
}

async function finishWithFutureAction(payload, action) {
  if (!state.focus?.id) throw new Error("A sessão não está mais disponível.");
  const latest = await api(`/focus/sessions/${state.focus.id}`);
  applyFocus(latest);
  const result = await finishFocus({...payload, version: latest.version, future_blocks_action: action});
  toast(result.idempotent ? "Sessão já estava finalizada." : "Sessão finalizada e registrada no histórico.");
  return result;
}

function resolveFutureTopicBlocks(payload) {
  showDialog({
    title: "Defina os blocos futuros",
    message: "Este tópico ainda possui blocos automáticos futuros. Escolha um destino para eles. Blocos manuais não serão alterados.",
    actions: [
      {label: "Redistribuir no planejamento", className: "primary", run: () => finishWithFutureAction(payload, "replan")},
      {label: "Usar o próximo tópico", run: () => finishWithFutureAction(payload, "next_topic")},
      {label: "Manter como revisão", run: () => finishWithFutureAction(payload, "review")},
      {label: "Voltar ao foco"},
    ],
  });
}

function openFinishDialog() {
  if (!state.focus || finalizing || elapsedSeconds() < 1) return;
  const hasTopic = Boolean(state.focus.topic_id);
  const previous = document.activeElement;
  const outcomes = [
    ["continue", "Ainda não terminei"],
    ["completed", "Concluí"],
    ["advance", "Concluí e quero avançar ao próximo"],
    ["review", "Quero revisar depois"],
  ];
  dialogRoot.innerHTML = `<div class="focus-dialog-backdrop"><section class="focus-dialog" role="dialog" aria-modal="true"><h2>Encerrar por hoje</h2><p>Serão registrados ${formatDuration(elapsedSeconds())} de foco real.</p><form id="finish-form" class="focus-form">${hasTopic ? `<fieldset><legend>Como ficou este tópico?</legend>${outcomes.map(([value, label], index) => `<label><input type="radio" name="topic_outcome" value="${value}" ${index === 0 ? "checked" : ""}> ${label}</label>`).join("")}</fieldset><label data-future-action hidden>Blocos automáticos futuros<select name="future_blocks_action"><option value="replan">Redistribuir no próximo planejamento</option><option value="next_topic">Converter para o próximo tópico elegível</option><option value="review">Manter como revisão</option></select></label>` : ""}<p class="form-error" data-finish-error></p><div class="focus-dialog-actions"><button class="button" type="button" data-finish-close>Continuar foco</button><button class="button primary" type="submit">Registrar sessão</button></div></form></section></div>`;
  const backdrop = dialogRoot.firstElementChild;
  const form = backdrop.querySelector("#finish-form");
  const future = form.querySelector("[data-future-action]");
  const updateFuture = () => {
    if (!future) return;
    const outcome = new FormData(form).get("topic_outcome");
    future.hidden = !["completed", "advance"].includes(outcome);
  };
  form.querySelectorAll("[name=topic_outcome]").forEach(input => input.addEventListener("change", updateFuture));
  backdrop.querySelector("[data-finish-close]")?.addEventListener("click", () => {
    dialogRoot.replaceChildren();
    previous?.focus?.();
  });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const values = new FormData(form);
    const outcome = values.get("topic_outcome") || "continue";
    const payload = {version: state.focus.version, topic_outcome: outcome};
    if (["completed", "advance"].includes(outcome)) payload.future_blocks_action = values.get("future_blocks_action");
    if (noteIsMeaningful()) payload.note = notePayload();
    finalizing = true;
    backdrop.querySelectorAll("button, input, select").forEach(item => { item.disabled = true; });
    try {
      const result = await finishFocus(payload);
      dialogRoot.replaceChildren();
      toast(result.idempotent ? "Sessão já estava finalizada." : "Sessão finalizada e registrada no histórico.");
    } catch (error) {
      if (error.code === "future_topic_blocks_need_resolution") {
        resolveFutureTopicBlocks(payload);
        return;
      }
      if (error.code === "focus_version_conflict") await refreshFromServer(true);
      const label = backdrop.querySelector("[data-finish-error]");
      if (label) label.textContent = error.message;
      backdrop.querySelectorAll("button, input, select").forEach(item => { item.disabled = false; });
    } finally {
      finalizing = false;
      if (state.mode === "active") renderFocus();
    }
  });
  window.setTimeout(() => (form.querySelector("input") || form.querySelector("button"))?.focus(), 0);
}

async function loadActiveConflict() {
  const active = await api("/focus/active");
  if (!active) {
    state.activeConflict = null;
    state.mode = plannedId ? "ready" : "setup";
    return renderFocus();
  }
  if (activeMatchesRequest(active)) {
    state.activeConflict = null;
    return useFocus(active);
  }
  state.activeConflict = active;
  state.mode = "conflict";
  renderFocus();
}

async function handleFocusError(error) {
  if (error.code === "focus_version_conflict") {
    toast("A sessão mudou em outra aba. Exibindo a versão atual.");
    await refreshFromServer(true);
    return;
  }
  if (error.code === "focus_session_already_active") {
    await loadActiveConflict();
    return;
  }
  toast(error.message);
}

async function refreshFromServer(silent = false) {
  try {
    if (!state.focus?.id) {
      const active = await api("/focus/active");
      if (active && activeMatchesRequest(active)) return useFocus(active, {render: !silent});
      if (active && !state.activeConflict) {
        state.activeConflict = active;
        state.mode = "conflict";
        if (!silent) renderFocus();
      }
      return active;
    }
    const oldStatus = state.focus.status;
    const snapshot = await api(`/focus/sessions/${state.focus.id}`);
    applyFocus(snapshot);
    if (snapshot.note_id && !state.noteDirty && Number(state.note.id || 0) !== Number(snapshot.note_id)) await hydrateNote();
    if (oldStatus !== snapshot.status || state.mode !== "active" || !app.querySelector("[data-focus-elapsed]")) renderFocus();
    else {
      updateClock();
      syncClock();
    }
    syncPolling();
    return snapshot;
  } catch (error) {
    if (!silent) toast(error.message);
    return null;
  }
}

function scheduleRefresh() {
  window.clearTimeout(refreshDebounce);
  refreshDebounce = window.setTimeout(() => refreshFromServer(true).catch(() => {}), 120);
}

async function initialize() {
  state.mode = "loading";
  renderFocus();
  try {
    const [loadedStudies, active] = await Promise.all([api("/studies"), api("/focus/active")]);
    studies = loadedStudies;
    if (plannedId) {
      state.planned = await api(`/planned/${plannedId}`);
      state.studyId = state.planned.study_subject_id;
      state.topicId = state.planned.topic_id || null;
      state.plannedDurationMinutes = state.planned.planned_duration_minutes || DEFAULT_DURATION_MINUTES;
    } else if (studies.length) {
      if (!studies.some(study => study.id === Number(state.studyId))) state.studyId = studies[0].id;
      topics = await topicsFor(state.studyId);
      if (state.topicId && !topics.some(topic => topic.id === Number(state.topicId))) state.topicId = null;
    }
    if (active) {
      if (activeMatchesRequest(active)) await useFocus(active);
      else {
        state.activeConflict = active;
        state.mode = "conflict";
        renderFocus();
      }
    } else {
      state.mode = plannedId ? "ready" : "setup";
      renderFocus();
    }
  } catch (error) {
    renderError(error);
  }
}

window.addEventListener(DATA_CHANGED_EVENT, event => {
  const path = String(event.detail?.path || "");
  if (!path || path.includes("/focus") || path.includes("/sessions") || path.includes("/planned") || path.includes("/topics")) scheduleRefresh();
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshFromServer(true).catch(() => {});
});

initialize();
