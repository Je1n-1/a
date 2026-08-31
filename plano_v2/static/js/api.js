export async function api(path, options = {}) {
  const headers = {...(options.body instanceof FormData ? {} : {"Content-Type": "application/json"}), ...(options.headers || {})};
  const response = await fetch(`/api${path}`, {...options, headers});
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Não foi possível concluir a ação.");
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
