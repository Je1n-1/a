import {api} from "./api.js";

const app = document.querySelector("#focus-app");
const dialogRoot = document.querySelector("#focus-dialog-root");
const toastRoot = document.querySelector("#focus-toast-root");
const query = new URLSearchParams(window.location.search);
const plannedParam = query.get("planned_id");
const plannedId = /^\d+$/.test(plannedParam || "") ? Number(plannedParam) : null;

let freeSessionKey = query.get("focus_session");
if (!plannedId && !freeSessionKey) {
  freeSessionKey = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  query.set("focus_session", freeSessionKey);
  window.history.replaceState({}, "", `${window.location.pathname}?${query.toString()}`);
}

const storageKey = `plano.focus.v1.${plannedId ? `planned-${plannedId}` : `free-${freeSessionKey}`}`;
const defaultDurationSeconds = 50 * 60;
const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[char]));

let studies = [];
let topics = [];
let clock = null;
let noteSaveTimer = null;
let noteSaving = false;
let noteSavePromise = null;
let noteRevision = 0;
let noteSavedRevision = 0;
let finalizing = false;
let state = loadStoredState() || createState();

// Se a página foi fechada entre uma alteração local e a resposta do autosave,
// mantenha a cópia local como pendente para que ela seja enviada novamente.
if (["saving", "error"].includes(state.noteStatus)) {
  noteRevision = 1;
  state.noteStatus = "saving";
  state.noteError = "";
}

function createState(values = {}) {
  return {
    version: 1,
    plannedId,
    phase: "setup",
    studySubjectId: null,
    topicId: null,
    subjectName: "",
    topicName: "",
    plannedDurationSeconds: defaultDurationSeconds,
    accumulatedMs: 0,
    startedAt: null,
    sessionStartedAt: null,
    completedSessionId: null,
    completedAt: null,
    note: {id: null, title: "", tags: "", content: ""},
    noteView: "editor",
    noteStatus: "saved",
    noteError: "",
    ...values,
  };
}

function loadStoredState() {
  try {
    const stored = JSON.parse(window.localStorage.getItem(storageKey) || "null");
    if (!stored || stored.version !== 1 || Number(stored.plannedId || 0) !== Number(plannedId || 0)) return null;
    const recovered = createState(stored);
    recovered.note = {...createState().note, ...(stored.note || {})};
    recovered.accumulatedMs = Math.max(0, Number(recovered.accumulatedMs) || 0);
    recovered.startedAt = recovered.startedAt ? Number(recovered.startedAt) : null;
    recovered.sessionStartedAt = recovered.sessionStartedAt ? Number(recovered.sessionStartedAt) : null;
    if (!["setup", "ready", "running", "paused", "finishing", "completed", "completion_pending_note"].includes(recovered.phase)) recovered.phase = "setup";
    return recovered;
  } catch (_) {
    return null;
  }
}

function persist() {
  try { window.localStorage.setItem(storageKey, JSON.stringify(state)); } catch (_) { /* A sessão continua funcional sem armazenamento local. */ }
}

function clearPersisted() {
  try { window.localStorage.removeItem(storageKey); } catch (_) { /* nothing to clear */ }
}

function elapsedMs() {
  const active = state.phase === "running" || state.phase === "finishing";
  return Math.max(0, state.accumulatedMs + (active && state.startedAt ? Date.now() - state.startedAt : 0));
}

function formatDuration(milliseconds) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  return [hours, minutes, remainder].map((value, index) => index === 0 && hours < 1 ? null : String(value).padStart(2, "0")).filter(value => value !== null).join(":");
}

function formatMinutes(seconds) {
  const minutes = Math.max(1, Math.round(Number(seconds || 0) / 60));
  return `${minutes} min`;
}

function saoPauloDateISO(value) {
  const parts = new Intl.DateTimeFormat("en-CA", {timeZone: "America/Sao_Paulo", year: "numeric", month: "2-digit", day: "2-digit"}).formatToParts(value);
  const map = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return `${map.year}-${map.month}-${map.day}`;
}

function toast(message) {
  const element = document.createElement("div");
  element.className = "focus-toast";
  element.textContent = message;
  toastRoot.replaceChildren(element);
  window.setTimeout(() => element.remove(), 4200);
}

function statusText() {
  if (state.noteStatus === "saving") return "Salvando…";
  if (state.noteStatus === "error") return "Erro ao salvar";
  return "Salvo";
}

function updateNoteStatus() {
  const label = app.querySelector("[data-note-status]");
  if (!label) return;
  label.className = `note-status ${state.noteStatus}`;
  label.textContent = statusText();
  label.title = state.noteError || "";
}

function safeInlineMarkdown(source) {
  return source
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

function safeMarkdown(source) {
  const lines = escapeHtml(source).split("\n");
  let inList = false;
  const result = [];
  const closeList = () => { if (inList) { result.push("</ul>"); inList = false; } };
  for (const line of lines) {
    if (line.startsWith("### ")) { closeList(); result.push(`<h4>${safeInlineMarkdown(line.slice(4))}</h4>`); }
    else if (line.startsWith("## ")) { closeList(); result.push(`<h3>${safeInlineMarkdown(line.slice(3))}</h3>`); }
    else if (line.startsWith("# ")) { closeList(); result.push(`<h2>${safeInlineMarkdown(line.slice(2))}</h2>`); }
    else if (/^[-*]\s+/.test(line)) { if (!inList) { result.push("<ul>"); inList = true; } result.push(`<li>${safeInlineMarkdown(line.replace(/^[-*]\s+/, ""))}</li>`); }
    else { closeList(); result.push(line ? `<p>${safeInlineMarkdown(line)}</p>` : "<br>"); }
  }
  closeList();
  return result.join("") || "<p class=\"muted\">Ainda não há anotações.</p>";
}

function noteIsMeaningful() {
  return Boolean(state.note.id || state.note.title.trim() || state.note.tags.trim() || state.note.content.trim());
}

function notePayload() {
  return {
    study_subject_id: Number(state.studySubjectId),
    topic_id: state.topicId ? Number(state.topicId) : null,
    planned_session_id: state.plannedId || null,
    title: state.note.title.trim() || `Anotação de ${state.subjectName || "estudo"}`,
    content_markdown: state.note.content,
    tags: state.note.tags,
    status: "draft",
  };
}

function applyRemoteNote(note) {
  if (!note) return;
  state.note.id = note.id || state.note.id;
  state.note.title = note.title ?? state.note.title;
  state.note.tags = Array.isArray(note.tags) ? note.tags.join(", ") : (note.tags ?? state.note.tags);
  state.note.content = note.content_markdown ?? note.content ?? state.note.content;
}

function markNoteDirty() {
  noteRevision += 1;
  state.noteStatus = "saving";
  state.noteError = "";
  persist();
  updateNoteStatus();
  window.clearTimeout(noteSaveTimer);
  noteSaveTimer = window.setTimeout(() => { saveNote().catch(() => {}); }, 800);
}

async function saveNote() {
  window.clearTimeout(noteSaveTimer);
  if (!noteIsMeaningful()) {
    state.noteStatus = "saved";
    state.noteError = "";
    noteSavedRevision = noteRevision;
    persist();
    updateNoteStatus();
    return null;
  }
  if (!state.studySubjectId) throw new Error("Escolha uma matéria antes de salvar as anotações.");
  if (noteSaving) return noteSavePromise;
  const revision = noteRevision;
  noteSaving = true;
  state.noteStatus = "saving";
  state.noteError = "";
  persist();
  updateNoteStatus();
  noteSavePromise = (async () => {
    try {
      const saved = state.note.id
        ? await api(`/notes/${state.note.id}`, {method: "PATCH", body: JSON.stringify(notePayload())})
        : await api("/notes", {method: "POST", body: JSON.stringify(notePayload())});
      applyRemoteNote(saved);
      noteSavedRevision = revision;
      state.noteStatus = "saved";
      state.noteError = "";
      persist();
      updateNoteStatus();
      if (revision !== noteRevision) window.setTimeout(() => { saveNote().catch(() => {}); }, 0);
      return saved;
    } catch (error) {
      state.noteStatus = "error";
      state.noteError = error.message;
      persist();
      updateNoteStatus();
      throw error;
    } finally {
      noteSaving = false;
      noteSavePromise = null;
    }
  })();
  return noteSavePromise;
}

async function flushNotes() {
  while (noteIsMeaningful() && noteSavedRevision !== noteRevision) await saveNote();
}

async function hydrateRemoteNote() {
  if (!state.note.id || noteRevision !== noteSavedRevision) return;
  try {
    applyRemoteNote(await api(`/notes/${state.note.id}`));
    state.noteStatus = "saved";
    persist();
  } catch (_) {
    // O rascunho local continua sendo a cópia de recuperação caso a rede falhe.
  }
}

async function topicsFor(studyId) {
  if (!studyId) return [];
  const detail = await api(`/studies/${studyId}`);
  return [...detail.groups.flatMap(group => group.topics), ...detail.ungrouped_topics];
}

function selectedStudy() {
  return studies.find(item => item.id === Number(state.studySubjectId));
}

function subjectOptions() {
  return studies.map(study => `<option value="${study.id}" ${study.id === Number(state.studySubjectId) ? "selected" : ""}>${escapeHtml(study.name)}</option>`).join("");
}

function topicOptions() {
  return `<option value="">Sem tópico</option>${topics.map(topic => `<option value="${topic.id}" ${topic.id === Number(state.topicId) ? "selected" : ""}>${escapeHtml(topic.name)}</option>`).join("")}`;
}

function renderLoading() {
  app.innerHTML = `<section class="focus-card focus-loading"><span class="tag">PREPARANDO</span><h1>Organizando sua sessão…</h1><p class="muted">Carregando matéria, tópico e rascunho de anotações.</p></section>`;
}

function renderSetup() {
  stopClock();
  app.innerHTML = `<section class="focus-setup focus-card"><span class="tag">SESSÃO LIVRE</span><h1>Em que você quer focar?</h1><p class="muted">Escolha uma matéria e, se quiser, um tópico. A sessão permanecerá disponível se esta aba for recarregada.</p>${studies.length ? `<form id="free-session-form" class="focus-form"><label>Matéria<select name="study_subject_id" id="focus-study" required>${subjectOptions()}</select></label><label>Tópico<select name="topic_id" id="focus-topic">${topicOptions()}</select></label><label>Duração planejada (minutos)<input name="planned_duration" type="number" min="1" max="1440" value="${Math.max(1, Math.round(state.plannedDurationSeconds / 60))}" required></label><div class="focus-form-actions"><a class="button ghost" href="/">Voltar ao plano</a><button class="button primary" type="submit">Preparar sessão</button></div></form>` : `<div class="empty"><strong>Não há matérias disponíveis</strong><span>Crie um estudo antes de iniciar uma sessão livre.</span><a class="button primary" href="/studies">Abrir estudos</a></div>`}</section>`;
  const form = app.querySelector("#free-session-form");
  if (!form) return;
  form.querySelector("#focus-study").addEventListener("change", async event => {
    state.studySubjectId = Number(event.target.value);
    state.topicId = null;
    state.subjectName = selectedStudy()?.name || "";
    state.topicName = "";
    persist();
    try { topics = await topicsFor(state.studySubjectId); } catch (error) { toast(error.message); topics = []; }
    renderSetup();
  });
  form.addEventListener("submit", event => {
    event.preventDefault();
    const values = new FormData(form);
    const minutes = Number(values.get("planned_duration"));
    if (!Number.isFinite(minutes) || minutes < 1) return toast("Informe uma duração de pelo menos um minuto.");
    state.studySubjectId = Number(values.get("study_subject_id"));
    state.topicId = values.get("topic_id") ? Number(values.get("topic_id")) : null;
    state.subjectName = selectedStudy()?.name || "";
    state.topicName = topics.find(topic => topic.id === state.topicId)?.name || "";
    state.plannedDurationSeconds = Math.round(minutes * 60);
    state.phase = "ready";
    persist();
    renderFocus();
  });
}

function renderCompleted() {
  stopClock();
  const pending = state.phase === "completion_pending_note";
  app.innerHTML = `<section class="focus-complete focus-card"><span class="tag ${pending ? "warning" : ""}">${pending ? "ANOTAÇÃO PENDENTE" : "SESSÃO FINALIZADA"}</span><h1>${pending ? "A sessão foi registrada" : "Bom trabalho."}</h1><p class="muted">${pending ? "A sessão foi salva, mas a anotação ainda precisa ser finalizada. Seus dados continuam guardados." : `Foram registrados ${formatDuration(state.accumulatedMs)} de foco real.`}</p><div class="focus-form-actions">${pending ? '<button class="button primary" type="button" data-retry-note>Finalizar anotação</button>' : ""}<a class="button" href="/history">Ver histórico</a><a class="button ghost" href="/focus">Nova sessão livre</a><a class="button ghost" href="/">Voltar ao plano</a></div></section>`;
  app.querySelector("[data-retry-note]")?.addEventListener("click", retryNoteFinalization);
}

function renderFocus() {
  if (state.phase === "setup") return renderSetup();
  if (state.phase === "completed" || state.phase === "completion_pending_note") return renderCompleted();
  const elapsed = elapsedMs();
  const remaining = Math.max(0, state.plannedDurationSeconds * 1000 - elapsed);
  const isRunning = state.phase === "running";
  const isPaused = state.phase === "paused";
  const isReady = state.phase === "ready";
  const canFinish = (isRunning || isPaused) && elapsed >= 1000 && !finalizing;
  const primaryControl = isReady
    ? '<button class="button primary" type="button" data-start-session>Iniciar</button>'
    : isRunning
      ? '<button class="button" type="button" data-pause-session>Pausar</button>'
      : isPaused
        ? '<button class="button primary" type="button" data-resume-session>Continuar</button>'
        : '<button class="button" type="button" disabled>Finalizando…</button>';
  app.innerHTML = `<div class="focus-grid"><section class="focus-card focus-timer-card"><div class="focus-session-meta"><span class="tag">${state.plannedId ? "BLOCO PLANEJADO" : "SESSÃO LIVRE"}</span><span class="focus-phase">${isReady ? "Pronta para começar" : isRunning ? "Em foco" : isPaused ? "Pausada" : "Finalizando…"}</span></div><h1>${escapeHtml(state.subjectName || "Matéria")}</h1><p class="focus-topic">${escapeHtml(state.topicName || "Sem tópico definido")}</p><div class="focus-timer" aria-label="Tempo decorrido" data-focus-elapsed>${formatDuration(elapsed)}</div><div class="focus-timer-details"><div><span>Tempo decorrido</span><strong data-focus-elapsed-small>${formatDuration(elapsed)}</strong></div><div><span>Tempo restante</span><strong data-focus-remaining>${formatDuration(remaining)}</strong></div><div><span>Planejado</span><strong>${formatMinutes(state.plannedDurationSeconds)}</strong></div></div><p class="focus-overtime ${remaining === 0 && elapsed ? "visible" : ""}" data-focus-overtime>${remaining === 0 && elapsed ? "Você concluiu o tempo planejado. Pode finalizar quando quiser." : ""}</p><div class="focus-controls">${primaryControl}<button class="button" type="button" data-finish-session ${canFinish ? "" : "disabled"}>${finalizing ? "Finalizando…" : "Finalizar sessão"}</button><button class="button danger" type="button" data-cancel-session ${finalizing ? "disabled" : ""}>Cancelar</button></div></section><aside class="focus-card focus-notes-card"><div class="focus-notes-heading"><div><span class="tag">ANOTAÇÕES</span><h2>Seu caderno da sessão</h2></div><span class="note-status ${state.noteStatus}" data-note-status title="${escapeHtml(state.noteError)}">${statusText()}</span></div><div class="focus-note-tabs" role="tablist" aria-label="Anotações"><button class="note-tab ${state.noteView === "editor" ? "active" : ""}" type="button" data-note-view="editor" role="tab" aria-selected="${state.noteView === "editor"}">Escrever</button><button class="note-tab ${state.noteView === "preview" ? "active" : ""}" type="button" data-note-view="preview" role="tab" aria-selected="${state.noteView === "preview"}">Prévia</button><button class="button ghost focus-save-note" type="button" data-save-note>Salvar agora</button></div>${state.noteView === "preview" ? `<article class="markdown-preview" aria-label="Prévia segura do Markdown">${safeMarkdown(state.note.content)}</article>` : `<div class="focus-note-editor"><label>Título<input id="note-title" value="${escapeHtml(state.note.title)}" placeholder="Ex.: Ideias-chave da sessão"></label><label>Tags<input id="note-tags" value="${escapeHtml(state.note.tags)}" placeholder="ex.: estudos, revisão"></label><label class="focus-note-content">Markdown<textarea id="note-content" placeholder="Escreva suas anotações em Markdown…">${escapeHtml(state.note.content)}</textarea></label></div>`}</aside></div>`;
  bindFocusActions();
  updateClock();
  if (isRunning || state.phase === "finishing") startClock(); else stopClock();
}

function bindFocusActions() {
  app.querySelector("[data-start-session]")?.addEventListener("click", startSession);
  app.querySelector("[data-pause-session]")?.addEventListener("click", pauseSession);
  app.querySelector("[data-resume-session]")?.addEventListener("click", resumeSession);
  app.querySelector("[data-finish-session]")?.addEventListener("click", finishSession);
  app.querySelector("[data-cancel-session]")?.addEventListener("click", cancelSession);
  app.querySelector("[data-save-note]")?.addEventListener("click", async () => {
    try { await flushNotes(); toast("Anotação salva."); } catch (error) { toast(error.message); }
  });
  app.querySelectorAll("[data-note-view]").forEach(button => button.addEventListener("click", () => {
    state.noteView = button.dataset.noteView;
    persist();
    renderFocus();
  }));
  [["#note-title", "title"], ["#note-tags", "tags"], ["#note-content", "content"]].forEach(([selector, field]) => {
    app.querySelector(selector)?.addEventListener("input", event => {
      state.note[field] = event.target.value;
      markNoteDirty();
    });
  });
}

function updateClock() {
  const elapsed = elapsedMs();
  const remaining = Math.max(0, state.plannedDurationSeconds * 1000 - elapsed);
  app.querySelectorAll("[data-focus-elapsed]").forEach(element => { element.textContent = formatDuration(elapsed); });
  app.querySelectorAll("[data-focus-elapsed-small]").forEach(element => { element.textContent = formatDuration(elapsed); });
  app.querySelectorAll("[data-focus-remaining]").forEach(element => { element.textContent = formatDuration(remaining); });
  const overtime = app.querySelector("[data-focus-overtime]");
  if (overtime) {
    overtime.classList.toggle("visible", remaining === 0 && elapsed > 0);
    overtime.textContent = remaining === 0 && elapsed ? "Você concluiu o tempo planejado. Pode finalizar quando quiser." : "";
  }
}

function startClock() {
  if (clock) return;
  clock = window.setInterval(updateClock, 250);
}

function stopClock() {
  if (clock) window.clearInterval(clock);
  clock = null;
}

function startSession() {
  if (state.phase !== "ready") return;
  const now = Date.now();
  state.phase = "running";
  state.startedAt = now;
  state.sessionStartedAt ||= now;
  persist();
  renderFocus();
}

function pauseSession() {
  if (state.phase !== "running") return;
  state.accumulatedMs += Math.max(0, Date.now() - state.startedAt);
  state.startedAt = null;
  state.phase = "paused";
  persist();
  renderFocus();
}

function resumeSession() {
  if (state.phase !== "paused") return;
  state.startedAt = Date.now();
  state.phase = "running";
  persist();
  renderFocus();
}

async function finishSession() {
  if (finalizing || !["running", "paused"].includes(state.phase) || elapsedMs() < 1000) return;
  const previousPhase = state.phase;
  const elapsed = elapsedMs();
  const endedAt = Date.now();
  finalizing = true;
  state.phase = "finishing";
  persist();
  renderFocus();
  let session = null;
  try {
    if (noteIsMeaningful()) await flushNotes();
    session = await api("/sessions", {method: "POST", body: JSON.stringify({
      study_subject_id: Number(state.studySubjectId),
      topic_id: state.topicId ? Number(state.topicId) : null,
      planned_session_id: state.plannedId || null,
      date: saoPauloDateISO(new Date(state.sessionStartedAt || endedAt)),
      started_at: new Date(state.sessionStartedAt || endedAt).toISOString(),
      ended_at: new Date(endedAt).toISOString(),
      duration_seconds: Math.max(1, Math.round(elapsed / 1000)),
      entry_method: "timer",
      notes: "",
    })});
    state.accumulatedMs = elapsed;
    state.startedAt = null;
    state.completedSessionId = session.id;
    state.completedAt = endedAt;
    if (state.note.id) await api(`/notes/${state.note.id}/finalize`, {method: "POST", body: JSON.stringify({study_session_id: session.id})});
    state.phase = "completed";
    state.noteStatus = "saved";
    state.noteError = "";
    persist();
    toast("Sessão finalizada e registrada no histórico.");
  } catch (error) {
    if (session) {
      state.accumulatedMs = elapsed;
      state.startedAt = null;
      state.completedSessionId = session.id;
      state.completedAt = endedAt;
      state.phase = "completion_pending_note";
      state.noteStatus = "error";
      state.noteError = error.message;
      persist();
      toast("A sessão foi registrada; falta finalizar a anotação.");
    } else {
      state.phase = previousPhase;
      if (previousPhase === "running" && !state.startedAt) state.startedAt = Date.now();
      persist();
      toast(error.message);
    }
  } finally {
    finalizing = false;
    renderFocus();
  }
}

async function retryNoteFinalization() {
  if (finalizing || !state.completedSessionId || !state.note.id) return;
  finalizing = true;
  try {
    await api(`/notes/${state.note.id}/finalize`, {method: "POST", body: JSON.stringify({study_session_id: state.completedSessionId})});
    state.phase = "completed";
    state.noteStatus = "saved";
    state.noteError = "";
    persist();
    toast("Anotação finalizada.");
  } catch (error) {
    state.noteStatus = "error";
    state.noteError = error.message;
    persist();
    toast(error.message);
  } finally {
    finalizing = false;
    renderFocus();
  }
}

function showDialog({title, message, actions}) {
  const previousFocus = document.activeElement;
  dialogRoot.innerHTML = `<div class="focus-dialog-backdrop"><section class="focus-dialog" role="dialog" aria-modal="true" aria-labelledby="focus-dialog-title"><h2 id="focus-dialog-title">${escapeHtml(title)}</h2><p>${escapeHtml(message)}</p><p class="form-error" data-dialog-error></p><div class="focus-dialog-actions">${actions.map((action, index) => `<button class="button ${action.className || ""}" type="button" data-dialog-action="${index}">${escapeHtml(action.label)}</button>`).join("")}</div></section></div>`;
  const backdrop = dialogRoot.firstElementChild;
  const close = () => {
    dialogRoot.replaceChildren();
    document.removeEventListener("keydown", keydown);
    previousFocus?.focus?.();
  };
  const keydown = event => { if (event.key === "Escape" && !backdrop.dataset.busy) close(); };
  document.addEventListener("keydown", keydown);
  backdrop.addEventListener("click", event => { if (event.target === backdrop && !backdrop.dataset.busy) close(); });
  backdrop.querySelectorAll("[data-dialog-action]").forEach(button => button.addEventListener("click", async () => {
    const action = actions[Number(button.dataset.dialogAction)];
    if (!action.run) return close();
    backdrop.dataset.busy = "true";
    backdrop.querySelectorAll("button").forEach(item => { item.disabled = true; });
    try { await action.run(); close(); } catch (error) {
      const errorLabel = backdrop.querySelector("[data-dialog-error]");
      errorLabel.textContent = error.message;
      backdrop.querySelectorAll("button").forEach(item => { item.disabled = false; });
      delete backdrop.dataset.busy;
    }
  }));
  window.setTimeout(() => backdrop.querySelector("button")?.focus(), 0);
}

function abandonSession(message) {
  stopClock();
  clearPersisted();
  state.phase = "cancelled";
  app.innerHTML = `<section class="focus-complete focus-card"><span class="tag">SESSÃO CANCELADA</span><h1>Sessão cancelada.</h1><p class="muted">${escapeHtml(message)}</p><div class="focus-form-actions"><a class="button primary" href="/focus">Nova sessão livre</a><a class="button ghost" href="/">Voltar ao plano</a></div></section>`;
}

function cancelSession() {
  if (finalizing || state.phase === "finishing") return;
  const withNote = noteIsMeaningful();
  showDialog({
    title: "Cancelar sessão?",
    message: withNote ? "Você pode guardar o rascunho das anotações para continuar depois ou descartá-lo. O tempo desta sessão não entrará no histórico." : "O tempo desta sessão não entrará no histórico.",
    actions: [
      {label: "Continuar sessão"},
      ...(withNote ? [{label: "Guardar rascunho", className: "primary", run: async () => { await flushNotes(); abandonSession("O rascunho foi guardado para consulta futura."); }}] : []),
      {label: withNote ? "Descartar rascunho e cancelar" : "Cancelar sessão", className: "danger", run: async () => {
        if (state.note.id) await api(`/notes/${state.note.id}`, {method: "DELETE"});
        abandonSession(withNote ? "O rascunho e a sessão foram descartados." : "Você pode iniciar outra sessão quando quiser.");
      }},
    ],
  });
}

async function hydratePlannedSession() {
  if (state.studySubjectId) {
    state.phase = state.phase === "setup" ? "ready" : state.phase;
    persist();
    return;
  }
  const planned = await api(`/planned/${plannedId}`);
  state = createState({
    plannedId,
    phase: "ready",
    studySubjectId: planned.study_subject_id,
    topicId: planned.topic_id || null,
    subjectName: planned.subject_name || "Matéria",
    topicName: planned.topic_name || "",
    plannedDurationSeconds: Math.max(1, Number(planned.planned_duration_minutes || 25)) * 60,
  });
  persist();
}

async function hydrateFreeSession() {
  if (!studies.length) return;
  state.studySubjectId ||= studies[0].id;
  state.subjectName = selectedStudy()?.name || state.subjectName;
  topics = await topicsFor(state.studySubjectId);
  if (state.topicId && !topics.some(topic => topic.id === Number(state.topicId))) {
    state.topicId = null;
    state.topicName = "";
  } else if (state.topicId) {
    state.topicName = topics.find(topic => topic.id === Number(state.topicId))?.name || state.topicName;
  }
  persist();
}

async function initialize() {
  renderLoading();
  try {
    studies = await api("/studies");
    if (plannedId) await hydratePlannedSession(); else await hydrateFreeSession();
    await hydrateRemoteNote();
    renderFocus();
    if (noteIsMeaningful() && noteSavedRevision !== noteRevision) {
      window.setTimeout(() => { saveNote().catch(() => {}); }, 0);
    }
  } catch (error) {
    stopClock();
    app.innerHTML = `<section class="focus-card focus-error"><span class="tag">NÃO FOI POSSÍVEL ABRIR</span><h1>Não foi possível preparar a sessão.</h1><p class="muted">${escapeHtml(error.message)}</p><div class="focus-form-actions"><a class="button" href="/">Voltar ao plano</a><button class="button primary" type="button" data-retry-focus>Tentar novamente</button></div></section>`;
    app.querySelector("[data-retry-focus]")?.addEventListener("click", initialize);
  }
}

window.addEventListener("beforeunload", event => {
  const active = ["running", "paused", "finishing"].includes(state.phase);
  const unsaved = noteSaving || state.noteStatus === "error" || noteSavedRevision !== noteRevision;
  if (active || unsaved) {
    event.preventDefault();
    event.returnValue = "";
  }
});
window.addEventListener("visibilitychange", () => { if (!document.hidden) updateClock(); });

initialize();
