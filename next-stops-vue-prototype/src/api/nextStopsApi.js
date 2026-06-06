const DATA_API_BASE = import.meta.env.VITE_NEXT_STOPS_API_BASE || "";
const ATTRACTION_API_BASE = import.meta.env.VITE_ATTRACTION_API_BASE || "";
const SAVED_KEY = "nextstops:vue-prototype:saved";
const PLACE_CACHE_KEY = "nextstops:vue-prototype:places";

const LOCATION_HINTS = {
  taipei_main: { lat: 25.0478, lon: 121.517, district: "中正區" },
  xinyi: { lat: 25.0339, lon: 121.5645, district: "信義區" },
  daan: { lat: 25.0262, lon: 121.5353, district: "大安區" },
  songshan: { lat: 25.0496, lon: 121.5777, district: "松山區" },
};

const MOOD_QUERIES = {
  relaxing_walk: ["公園", "步道", "河濱"],
  date: ["景觀", "文創", "餐廳"],
  solo_quiet: ["博物館", "書店", "紀念館"],
  photo: ["景點", "古蹟", "藝術"],
  rainy_backup: ["博物館", "美術館", "文創"],
  night_out: ["夜市", "商圈", "景觀"],
};

let placeCache = loadJson(PLACE_CACHE_KEY, []);

async function fetchJson(base, path, options = {}) {
  const response = await fetch(`${base}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || data.detail || `API 回傳 HTTP ${response.status}`);
  return data;
}

export async function getRecommendations(criteria) {
  const location = LOCATION_HINTS[criteria.location] || LOCATION_HINTS.taipei_main;
  const queries = MOOD_QUERIES[criteria.mood] || [""];
  const collected = [];
  const seen = new Set();

  for (const q of queries) {
    const data = await searchPlaces({
      q,
      lat: location.lat,
      lon: location.lon,
      radius_m: Math.max(1200, Number(criteria.distance || 30) * 90),
      limit: 12,
    });

    for (const place of data.results) {
      if (!seen.has(place.id)) {
        seen.add(place.id);
        collected.push(enrichPlace(place, criteria));
      }
    }
    if (collected.length >= 8) break;
  }

  const results = collected.sort((a, b) => b.score - a.score).slice(0, 5);
  rememberPlaces(results);
  return { count: results.length, results };
}

export async function getPlace(id) {
  const cached = placeCache.find((place) => place.id === id) || loadJson(SAVED_KEY, []).find((place) => place.id === id);
  if (cached) return cached;
  const data = await searchPlaces({ limit: 100 });
  const place = data.results.find((item) => item.id === id);
  if (!place) throw new Error("找不到這個地點");
  return place;
}

export async function getSavedPlaces() {
  return loadJson(SAVED_KEY, []);
}

export async function savePlace(item) {
  const saved = loadJson(SAVED_KEY, []);
  const next = [{ ...item, created_at: item.created_at || new Date().toISOString() }, ...saved.filter((entry) => entry.id !== item.id)];
  saveJson(SAVED_KEY, next);
  return next[0];
}

export async function updateSavedPlace(id, body) {
  const next = loadJson(SAVED_KEY, []).map((item) => (item.id === id ? { ...item, ...body } : item));
  saveJson(SAVED_KEY, next);
  return next.find((item) => item.id === id) || null;
}

export async function deleteSavedPlace(id) {
  saveJson(SAVED_KEY, loadJson(SAVED_KEY, []).filter((item) => item.id !== id));
  return { ok: true };
}

export async function getContext(lat, lon) {
  return fetchJson(DATA_API_BASE, `/api/context?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`);
}

async function searchPlaces(params) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null && value !== "") query.set(key === "lng" ? "lon" : key, value);
  }
  if (!query.has("limit")) query.set("limit", "20");
  const data = await fetchJson(ATTRACTION_API_BASE, `/places/search?${query.toString()}`);
  const results = (data.results || []).map(normalizeSearchResult);
  rememberPlaces(results);
  return { count: data.count ?? results.length, results };
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

function enrichPlace(place, criteria) {
  const text = `${place.name} ${place.category} ${(place.categories || []).join(" ")}`;
  const moodBonus = {
    relaxing_walk: /公園|河濱|步道|山|湖/,
    date: /景觀|文創|餐廳|藝術|夜景/,
    solo_quiet: /博物館|書店|紀念館|美術館|寺|廟/,
    photo: /景點|古蹟|街|景觀|藝術/,
    rainy_backup: /博物館|美術館|紀念館|文創/,
    night_out: /夜市|商圈|夜景|餐廳/,
  }[criteria.mood]?.test(text) ? 10 : 0;
  const budgetBonus = criteria.budget === "flexible" || criteria.budget === place.budget ? 6 : 0;
  const score = Math.max(1, Math.min(100, Math.round(place.score + moodBonus + budgetBonus)));
  return { ...place, score, reason: `${place.reason} 已依你的心情、時間與出發區域排序。` };
}

function labelCategory(value) {
  const labels = {
    scenic_spot: "景點",
    attraction: "景點",
    taipei_featured: "精選景點",
    museum: "博物館",
    gallery: "藝文",
    viewpoint: "景觀",
    restaurant: "餐飲",
    market: "市集",
    park: "公園",
  };
  return labels[value] || value || "景點";
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
  if (/餐廳|商圈|restaurant/.test(text)) return "flexible";
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

function saveJson(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}
