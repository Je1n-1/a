const DATA_CHANGED_EVENT = "plano:data-changed";
const STATE_CHANNEL_NAME = "plano-state";
const STATE_STORAGE_KEY = "plano:data-changed";
const MUTATION_METHODS = new Set(["POST", "PATCH", "PUT", "DELETE"]);

let stateChannel = null;
let stateChannelUnavailable = false;

function dispatchDataChanged(detail) {
  if (typeof window === "undefined" || typeof window.dispatchEvent !== "function") return;
  try {
    const DataChangedEvent = globalThis.CustomEvent || window.CustomEvent;
    if (typeof DataChangedEvent !== "function") return;
    window.dispatchEvent(new DataChangedEvent(DATA_CHANGED_EVENT, {detail}));
  } catch (_) {
    // Notifications must never make a successful API mutation fail.
  }
}

function getStateChannel() {
  if (stateChannel || stateChannelUnavailable) return stateChannel;
  const Channel = typeof globalThis !== "undefined" ? globalThis.BroadcastChannel : null;
  if (typeof Channel !== "function") {
    stateChannelUnavailable = true;
    return null;
  }
  try {
    stateChannel = new Channel(STATE_CHANNEL_NAME);
    stateChannel.addEventListener("message", (event) => {
      dispatchDataChanged(event.data);
    });
  } catch (_) {
    stateChannelUnavailable = true;
    stateChannel = null;
  }
  return stateChannel;
}

function publishStorageFallback(detail) {
  try {
    const storage = globalThis.localStorage;
    storage.setItem(STATE_STORAGE_KEY, JSON.stringify(detail));
  } catch (_) {
    // localStorage can be unavailable in private or restricted contexts.
  }
}

function notifyDataChanged(method, path) {
  const detail = {method, path, timestamp: Date.now()};
  dispatchDataChanged(detail);
  try {
    const channel = getStateChannel();
    if (channel) {
      channel.postMessage(detail);
      return;
    }
  } catch (_) {
    stateChannel = null;
    stateChannelUnavailable = true;
  }
  publishStorageFallback(detail);
}

function installStorageFallbackListener() {
  if (typeof window === "undefined" || typeof window.addEventListener !== "function") return;
  window.addEventListener("storage", (event) => {
    if (event.key !== STATE_STORAGE_KEY || !event.newValue) return;
    try {
      dispatchDataChanged(JSON.parse(event.newValue));
    } catch (_) {
      // Ignore unrelated or malformed storage values.
    }
  });
}

getStateChannel();
installStorageFallbackListener();

export async function api(path, options = {}) {
  const headers = {...(options.body instanceof FormData ? {} : {"Content-Type": "application/json"}), ...(options.headers || {})};
  let response;
  try {
    response = await fetch(`/api${path}`, {...options, headers});
  } catch (_) {
    throw new Error("Não foi possível conectar ao servidor. Verifique se o plano está em execução.");
  }
  const raw = response.status === 204 ? "" : await response.text();
  let payload = null;
  if (raw) {
    try { payload = JSON.parse(raw); } catch (_) { payload = null; }
  }
  if (!response.ok) {
    const error = new Error(payload?.error || `Não foi possível concluir a ação (erro ${response.status}).`);
    error.status = response.status;
    error.code = payload?.code;
    error.blockers = payload?.blockers;
    error.details = payload?.details;
    throw error;
  }
  const method = String(options.method || "GET").toUpperCase();
  if (MUTATION_METHODS.has(method)) notifyDataChanged(method, path);
  return payload;
}

export function localDateISO(value = new Date()) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function weekDates(first = new Date()) {
  const monday = new Date(first.getFullYear(), first.getMonth(), first.getDate());
  monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
  return Array.from({length: 7}, (_, index) => {
    const current = new Date(monday);
    current.setDate(monday.getDate() + index);
    return localDateISO(current);
  });
}
