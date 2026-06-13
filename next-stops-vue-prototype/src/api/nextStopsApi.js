const DATA_API_BASE = import.meta.env.VITE_NEXT_STOPS_API_BASE || "";
const SAVED_KEY = "nextstops:vue-prototype:saved";
const PLACE_CACHE_KEY = "nextstops:vue-prototype:places";
const SESSION_KEY = "nextstops:vue-prototype:session";
const AUTH_KEY = "nextstops:vue-prototype:auth";
const ADMIN_KEY = "nextstops:vue-prototype:admin";

let placeCache = loadJson(PLACE_CACHE_KEY, []);

async function fetchJson(base, path, options = {}) {
  const auth = getStoredAuth();
  const headers = {
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(auth?.token ? { Authorization: `Bearer ${auth.token}` } : {}),
    ...(options.headers || {}),
  };
  const response = await fetch(`${base}${path}`, {
    ...options,
    headers,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || data.detail || `API 回傳 HTTP ${response.status}`);
  return data;
}

export function getStoredAuth() {
  const auth = loadSessionJson(AUTH_KEY, null);
  if (auth) return auth;
  if (localStorage.getItem(AUTH_KEY)) localStorage.removeItem(AUTH_KEY);
  return null;
}

export function setStoredAuth(auth) {
  if (!auth) {
    sessionStorage.removeItem(AUTH_KEY);
    localStorage.removeItem(AUTH_KEY);
    return null;
  }
  sessionStorage.setItem(AUTH_KEY, JSON.stringify(auth));
  localStorage.removeItem(AUTH_KEY);
  if (auth.mode === "guest" && auth.user?.session_id) localStorage.setItem(SESSION_KEY, auth.user.session_id);
  return auth;
}

export function clearStoredAuth() {
  sessionStorage.removeItem(AUTH_KEY);
  localStorage.removeItem(AUTH_KEY);
}

export function getStoredAdminToken() {
  return sessionStorage.getItem(ADMIN_KEY) || "";
}

export function setStoredAdminToken(token) {
  const clean = String(token || "").trim();
  if (!clean) sessionStorage.removeItem(ADMIN_KEY);
  else sessionStorage.setItem(ADMIN_KEY, clean);
  return clean;
}

export function clearStoredAdminToken() {
  sessionStorage.removeItem(ADMIN_KEY);
}

async function fetchAdmin(path, options = {}) {
  const token = getStoredAdminToken();
  const headers = {
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(token ? { "X-Admin-Token": token } : {}),
    ...(options.headers || {}),
  };
  const response = await fetch(`${DATA_API_BASE}${path}`, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || data.detail || `Admin API 回傳 HTTP ${response.status}`);
  return data;
}

export async function verifyAdminToken(token) {
  setStoredAdminToken(token);
  return fetchAdmin("/api/admin/summary");
}

export function getAdminSummary() {
  return fetchAdmin("/api/admin/summary");
}

export function getAdminOverview() {
  return fetchAdmin("/api/admin/overview");
}

export function getAdminUsers() {
  return fetchAdmin("/api/admin/users");
}

export function deleteAdminUser(userId) {
  return fetchAdmin(`/api/admin/users/${encodeURIComponent(userId)}`, { method: "DELETE" });
}

export function getAdminRecommendations() {
  return fetchAdmin("/api/admin/recommendations");
}

export function getAdminFeedback() {
  return fetchAdmin("/api/admin/feedback");
}

export function getAdminPlaces() {
  return fetchAdmin("/api/admin/places");
}

export function rebuildAdminPlaces() {
  return fetchAdmin("/api/admin/places/rebuild", { method: "POST" });
}

export function startGuestSession() {
  const sessionId = getOrCreateAnonymousSession();
  const auth = {
    mode: "guest",
    token: "",
    user: {
      id: sessionId,
      provider: "guest",
      name: "訪客",
      account: "guest",
      email: "",
      avatar_url: "",
      session_id: sessionId,
      preferences: {},
    },
  };
  return setStoredAuth(auth);
}

export async function getAuthConfig() {
  return fetchJson(DATA_API_BASE, "/api/auth/config");
}

export async function registerAccount(payload) {
  return fetchJson(DATA_API_BASE, "/api/auth/register", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function loginAccount(payload) {
  const auth = await fetchJson(DATA_API_BASE, "/api/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return setStoredAuth({ mode: "account", ...auth });
}

export async function loginWithGoogleCredential(credential) {
  const auth = await fetchJson(DATA_API_BASE, "/api/auth/google", {
    method: "POST",
    body: JSON.stringify({ id_token: credential }),
  });
  return setStoredAuth({ mode: "google", ...auth });
}

export async function getCurrentUser() {
  const auth = getStoredAuth();
  if (!auth?.token) return auth?.user ? { user: auth.user } : null;
  const data = await fetchJson(DATA_API_BASE, "/api/auth/me");
  setStoredAuth({ ...auth, user: data.user });
  return data;
}

export async function updateUserPreferences(preferences) {
  const auth = getStoredAuth();
  if (!auth?.token) {
    const current = auth || startGuestSession();
    const next = {
      ...current,
      user: {
        ...(current.user || {}),
        preferences: {
          ...(current.user?.preferences || {}),
          ...preferences,
        },
      },
    };
    setStoredAuth(next);
    return next.user;
  }
  const data = await fetchJson(DATA_API_BASE, "/api/auth/preferences", {
    method: "PATCH",
    body: JSON.stringify(preferences),
  });
  setStoredAuth({ ...auth, user: data.user });
  return data.user;
}

export function updateFavoriteStarts(favoriteStarts) {
  return updateUserPreferences({ favoriteStarts });
}

export async function updateUserProfile(profile) {
  const auth = getStoredAuth();
  const cleanProfile = {
    name: String(profile?.name || "").trim(),
    avatar_url: String(profile?.avatar_url || "").trim(),
  };
  if (!auth?.token) {
    throw new Error("訪客模式不能編輯個人資料");
  }
  const data = await fetchJson(DATA_API_BASE, "/api/auth/profile", {
    method: "PATCH",
    body: JSON.stringify(cleanProfile),
  });
  setStoredAuth({ ...auth, user: data.user });
  return data.user;
}

export async function logoutAccount() {
  try {
    await fetchJson(DATA_API_BASE, "/api/auth/logout", { method: "POST" });
  } catch {
    // Local logout should still proceed if the API is offline.
  }
  clearStoredAuth();
}

export function logoutOnPageClose() {
  const auth = getStoredAuth();
  if (!auth?.token) {
    clearStoredAuth();
    return;
  }
  try {
    const payload = new Blob([JSON.stringify({})], { type: "application/json" });
    const url = `${DATA_API_BASE}/api/auth/logout?token=${encodeURIComponent(auth.token)}`;
    if (!navigator.sendBeacon?.(url, payload)) {
      fetch(url, { method: "POST", keepalive: true }).catch(() => {});
    }
  } catch {
    // Page is unloading; local session cleanup is the important part.
  }
  clearStoredAuth();
}

export async function deleteAccount() {
  await fetchJson(DATA_API_BASE, "/api/auth/account", { method: "DELETE" });
  clearStoredAuth();
}

export async function getRecommendations(criteria) {
  const data = await fetchJson(DATA_API_BASE, "/api/recommend", {
    method: "POST",
    body: JSON.stringify({
      criteria,
      session_id: getSessionId(),
      include_transport: true,
      limit: 5,
    }),
  });
  const results = (data.results || []).map(normalizeRecommendationResult);
  rememberPlaces(results);
  return { ...data, count: results.length, results };
}

export async function getPlace(id, criteria = {}) {
  try {
    const query = new URLSearchParams({
      session_id: getSessionId(),
      mood: criteria.mood || "relaxing_walk",
      distance: String(criteria.distance || 30),
      time: String(criteria.time || 120),
      budget: criteria.budget || "medium",
      weatherPreference: criteria.weatherPreference || "any",
    });
    if (criteria.lat !== null && criteria.lat !== undefined && criteria.lon !== null && criteria.lon !== undefined) {
      query.set("lat", String(criteria.lat));
      query.set("lon", String(criteria.lon));
    }
    if (Array.isArray(criteria.transportModes) && criteria.transportModes.length) {
      query.set("transportModes", criteria.transportModes.join(","));
    }
    const place = normalizeRecommendationResult(await fetchJson(DATA_API_BASE, `/api/places/${encodeURIComponent(id)}?${query.toString()}`));
    rememberPlaces([place]);
    return place;
  } catch {
    // Fall through to local cache/search so the prototype remains usable when the API is offline.
  }
  const cached = placeCache.find((place) => place.id === id) || loadJson(SAVED_KEY, []).find((place) => place.id === id);
  if (cached) return cached;
  const data = await searchPlaces({ limit: 100 });
  const place = data.results.find((item) => item.id === id);
  if (!place) throw new Error("找不到這個地點");
  return place;
}

export async function getSavedPlaces() {
  try {
    const data = await fetchJson(DATA_API_BASE, `/api/saved-places?session_id=${encodeURIComponent(getSessionId())}`);
    const saved = (data.saved || []).map(normalizeRecommendationResult);
    saveJson(SAVED_KEY, saved);
    rememberPlaces(saved);
    return saved;
  } catch {
    return loadJson(SAVED_KEY, []);
  }
}

export async function savePlace(item) {
  const payload = {
    session_id: getSessionId(),
    place: item,
    note: item.note || "",
  };
  try {
    const savedItem = normalizeRecommendationResult(await fetchJson(DATA_API_BASE, "/api/saved-places", {
      method: "POST",
      body: JSON.stringify(payload),
    }));
    const localSaved = loadJson(SAVED_KEY, []);
    saveJson(SAVED_KEY, [savedItem, ...localSaved.filter((entry) => entry.id !== savedItem.id)]);
    rememberPlaces([savedItem]);
    return savedItem;
  } catch {
    return savePlaceLocal(item);
  }
}

function savePlaceLocal(item) {
  const saved = loadJson(SAVED_KEY, []);
  const next = [{ ...item, created_at: item.created_at || new Date().toISOString() }, ...saved.filter((entry) => entry.id !== item.id)];
  saveJson(SAVED_KEY, next);
  return next[0];
}

export async function updateSavedPlace(id, body) {
  try {
    const savedItem = normalizeRecommendationResult(await fetchJson(DATA_API_BASE, `/api/saved-places/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ session_id: getSessionId(), ...body }),
    }));
    const next = loadJson(SAVED_KEY, []).map((item) => (item.id === id ? savedItem : item));
    saveJson(SAVED_KEY, next);
    rememberPlaces([savedItem]);
    return savedItem;
  } catch {
    return updateSavedPlaceLocal(id, body);
  }
}

function updateSavedPlaceLocal(id, body) {
  const next = loadJson(SAVED_KEY, []).map((item) => (item.id === id ? { ...item, ...body } : item));
  saveJson(SAVED_KEY, next);
  return next.find((item) => item.id === id) || null;
}

export async function deleteSavedPlace(id) {
  try {
    await fetchJson(DATA_API_BASE, `/api/saved-places/${encodeURIComponent(id)}?session_id=${encodeURIComponent(getSessionId())}`, {
      method: "DELETE",
    });
  } catch {
    // Keep local prototype behavior available when the API is offline.
  }
  saveJson(SAVED_KEY, loadJson(SAVED_KEY, []).filter((item) => item.id !== id));
  return { ok: true };
}

export async function submitRecommendationFeedback(placeId, feedbackType, requestId = "", note = "") {
  return fetchJson(DATA_API_BASE, "/api/recommendation-feedback", {
    method: "POST",
    body: JSON.stringify({
      session_id: getSessionId(),
      request_id: requestId,
      place_id: placeId,
      feedback_type: feedbackType,
      note,
    }),
  });
}

export async function getContext(lat, lon) {
  return fetchJson(DATA_API_BASE, `/api/context?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`);
}

export async function getMapboxConfig() {
  return fetchJson(DATA_API_BASE, "/api/mapbox-config");
}

export async function getRoute(origin, destination, transportModes = []) {
  return fetchJson(DATA_API_BASE, "/api/route", {
    method: "POST",
    body: JSON.stringify({ origin, destination, transportModes }),
  });
}

export function googleDirectionsUrl(origin, destination, mode = "TRANSIT") {
  const travelmode = {
    TRANSIT: "transit",
    BUS: "transit",
    MRT: "transit",
    WALKING: "walking",
    DRIVING: "driving",
    CAR: "driving",
    MOTORCYCLE: "two-wheeler",
    BICYCLE: "bicycling",
  }[mode] || "transit";
  const params = new URLSearchParams({
    api: "1",
    destination: destination.google_place_id || destination.place_id
      ? (destination.google_name || destination.name || destination.address || `${destination.lat},${destination.lon ?? destination.lng}`)
      : `${destination.lat},${destination.lon ?? destination.lng}`,
    travelmode,
  });
  if (destination.google_place_id || destination.place_id) {
    params.set("destination_place_id", destination.google_place_id || destination.place_id);
  }
  if (origin?.lat && (origin.lon || origin.lng)) {
    params.set("origin", `${origin.lat},${origin.lon ?? origin.lng}`);
  }
  return `https://www.google.com/maps/dir/?${params.toString()}`;
}

async function searchPlaces(params) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null && value !== "") query.set(key === "lng" ? "lon" : key, value);
  }
  if (!query.has("limit")) query.set("limit", "20");
  const data = await fetchJson(DATA_API_BASE, `/api/places/search?${query.toString()}`);
  const results = (data.results || []).map(normalizeSearchResult);
  rememberPlaces(results);
  return { count: data.count ?? results.length, results };
}

function normalizeRecommendationResult(place) {
  const scoreValue = Number(place.score ?? place.algorithm?.score);
  const score = Number.isFinite(scoreValue)
    ? Math.round(scoreValue <= 1 ? scoreValue * 100 : scoreValue)
    : 0;
  return {
    ...place,
    lng: place.lon ?? place.lng,
    lon: place.lon ?? place.lng,
    score,
    matched_travel_time: place.commute?.duration_seconds
      ? Math.round(place.commute.duration_seconds / 60)
      : place.matched_travel_time ?? place.travel_time_minutes ?? 28,
    travel_time_minutes: place.commute?.duration_seconds
      ? Math.round(place.commute.duration_seconds / 60)
      : place.travel_time_minutes ?? place.matched_travel_time ?? 28,
    weather_summary: place.weather_summary || place.context?.weather?.summary || "天氣資料已納入評分",
    aqi_value: place.aqi_value ?? place.context?.air_quality?.aqi ?? "--",
    aqi_status: place.aqi_status || place.context?.air_quality?.status || "unknown",
    route_hint: place.route_hint || routeHintFromTransport(place.transport),
  };
}

function normalizeSearchResult(result) {
  const place = result.place || result;
  const categories = Array.isArray(place.categories) ? place.categories.filter(Boolean) : [];
  const quality = Number(place.quality_score ?? result.quality_score ?? 0.55);
  const score = Math.round(Math.max(0, Math.min(1, Number(result.score ?? quality))) * 100);
  const distanceM = Number(result.distance_m ?? place.distance_m);
  const travelTime = Number.isFinite(distanceM) ? Math.max(8, Math.round(distanceM / 420)) : 28;
  const category = labelCategory(categories[0]);

  return {
    ...place,
    id: place.id,
    name: place.name,
    category,
    categories,
    address: place.address || `${place.district || "臺北市"} / 臺北市`,
    lat: place.lat,
    lng: place.lon ?? place.lng,
    lon: place.lon ?? place.lng,
    description: place.description || "資料來自台北景點搜尋平台，適合作為當下探索候選。",
    score,
    matched_travel_time: travelTime,
    travel_time_minutes: travelTime,
    budget: inferBudget(categories),
    weather_status: inferWeatherStatus(categories),
    weather_summary: "可依即時情境再確認",
    aqi_value: "--",
    aqi_status: "moderate",
    open_now: true,
    route_hint: "開啟地圖後確認實際路線與交通方式",
    reason: `${place.name} 位在${place.district || "臺北市"}，屬於${category}類型，約 ${travelTime} 分鐘可納入行程。`,
    backup_options: [],
    rating: place.rating ?? Math.round((3.8 + quality * 1.1) * 10) / 10,
  };
}

function labelCategory(value) {
  const labels = {
    scenic_spot: "景點",
    attraction: "景點",
    taipei_featured: "精選景點",
    museum: "博物館",
    gallery: "藝文",
    venue: "場館",
    viewpoint: "景觀",
    restaurant: "餐飲",
    market: "市集",
    park: "公園",
  };
  return labels[value] || value || "景點";
}

function routeHintFromTransport(transport) {
  const bus = transport?.nearest_bus_station;
  const mrt = transport?.nearest_mrt_station;
  if (mrt?.name_zh && mrt.distance_m !== undefined) return `鄰近捷運 ${mrt.name_zh}，約 ${mrt.distance_m} 公尺。`;
  if (bus?.name_zh && bus.distance_m !== undefined) return `鄰近公車站 ${bus.name_zh}，約 ${bus.distance_m} 公尺。`;
  return "已納入距離與即時情境評分；實際路線請用地圖確認。";
}

function getSessionId() {
  const auth = getStoredAuth();
  if (auth?.user?.session_id) return auth.user.session_id;
  return getOrCreateAnonymousSession();
}

function getOrCreateAnonymousSession() {
  const existing = localStorage.getItem(SESSION_KEY);
  if (existing && !String(existing).startsWith("user:")) return existing;
  const id = globalThis.crypto?.randomUUID
    ? globalThis.crypto.randomUUID()
    : `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  localStorage.setItem(SESSION_KEY, id);
  return id;
}

function inferWeatherStatus(categories) {
  const text = categories.join(" ");
  if (/博物館|美術館|紀念館|文創|gallery|museum/.test(text)) return "suitable";
  if (/公園|河濱|步道|viewpoint/.test(text)) return "watch";
  return "any";
}

function inferBudget(categories) {
  const text = categories.join(" ");
  if (/公園|河濱|古蹟|taipei_featured/.test(text)) return "low";
  if (/餐廳|restaurant/.test(text)) return "high";
  return "medium";
}

function rememberPlaces(places) {
  const byId = new Map(placeCache.map((place) => [place.id, place]));
  for (const place of places) byId.set(place.id, place);
  placeCache = Array.from(byId.values()).slice(-200);
  saveJson(PLACE_CACHE_KEY, placeCache);
}

function loadJson(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key) || JSON.stringify(fallback));
  } catch {
    return fallback;
  }
}

function loadSessionJson(key, fallback) {
  try {
    return JSON.parse(sessionStorage.getItem(key) || JSON.stringify(fallback));
  } catch {
    return fallback;
  }
}

function saveJson(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}
