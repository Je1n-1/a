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
    throw error;
  }
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
