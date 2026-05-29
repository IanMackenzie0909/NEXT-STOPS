const storedBase = localStorage.getItem("nextstops:apiBase");

export const API_BASE =
  import.meta.env.VITE_NEXT_STOPS_API_BASE || storedBase || "http://127.0.0.1:8790";

export async function apiFetch(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `NEXT STOPS API 回傳 HTTP ${response.status}`);
  }
  return data;
}

export function getPlaces(params = {}) {
  const query = new URLSearchParams(params);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch(`/api/places${suffix}`);
}

export function getPlace(id) {
  return apiFetch(`/api/places/${encodeURIComponent(id)}`);
}

export function getRecommendations(criteria) {
  return apiFetch("/api/recommendations", {
    method: "POST",
    body: JSON.stringify(criteria),
  });
}

export function getSavedPlaces() {
  return apiFetch("/api/saved-places");
}

export function savePlace(item) {
  return apiFetch("/api/saved-places", {
    method: "POST",
    body: JSON.stringify(item),
  });
}

export function updateSavedPlace(id, body) {
  return apiFetch(`/api/saved-places/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function deleteSavedPlace(id) {
  return apiFetch(`/api/saved-places/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function getContext(lat, lon) {
  return apiFetch(`/api/context?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`);
}
