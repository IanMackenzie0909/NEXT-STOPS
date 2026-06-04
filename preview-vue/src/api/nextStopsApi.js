const storedBase = localStorage.getItem("nextstops:apiBase");

export const API_BASE = import.meta.env.VITE_NEXT_STOPS_API_BASE || storedBase || "";

const PLACE_CACHE_KEY = "nextstops:places";
const SAVED_KEY = "nextstops:saved";

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

const CATEGORY_LABELS = {
  cafe: "咖啡",
  park: "公園",
  museum: "博物館",
  market: "市集",
  bookstore: "書店",
  riverside: "河濱",
  gallery: "藝文",
  restaurant: "餐飲",
  viewpoint: "景觀",
  scenic_spot: "景點",
  attraction: "景點",
  taipei_featured: "精選景點",
};

let placeCache = loadJson(PLACE_CACHE_KEY, []);

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
    throw new Error(data.error || data.detail || `Taipei Attraction API 回傳 HTTP ${response.status}`);
  }
  return data;
}

export async function getPlaces(params = {}) {
  const data = await searchPlaces(params);
  return data.results;
}

export async function getPlace(id) {
  const cached = findCachedPlace(id);
  if (cached) return cached;

  const data = await searchPlaces({ limit: 100 });
  const place = data.results.find((item) => item.id === id);
  if (!place) throw new Error("找不到這個地點");
  return place;
}

export async function getRecommendations(criteria) {
  const location = LOCATION_HINTS[criteria.location] || LOCATION_HINTS.taipei_main;
  const radius_m = Math.max(1200, Number(criteria.distance || 30) * 90);
  const queries = MOOD_QUERIES[criteria.mood] || [""];
  const collected = [];
  const seen = new Set();

  for (const q of queries) {
    const data = await searchPlaces({
      q,
      lat: location.lat,
      lon: location.lon,
      radius_m,
      limit: 12,
    });
    for (const place of data.results) {
      if (!seen.has(place.id)) {
        seen.add(place.id);
        collected.push(place);
      }
    }
    if (collected.length >= 8) break;
  }

  const ranked = collected
    .map((place) => enrichForCriteria(place, criteria))
    .sort((a, b) => Number(b.score || 0) - Number(a.score || 0))
    .slice(0, 5);

  rememberPlaces(ranked);
  return { count: ranked.length, results: ranked };
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
  const saved = loadJson(SAVED_KEY, []);
  const next = saved.map((item) => (item.id === id ? { ...item, ...body } : item));
  saveJson(SAVED_KEY, next);
  return next.find((item) => item.id === id) || null;
}

export async function deleteSavedPlace(id) {
  const next = loadJson(SAVED_KEY, []).filter((item) => item.id !== id);
  saveJson(SAVED_KEY, next);
  return { ok: true };
}

export async function getContext() {
  return {
    weather: {
      weather: "即時天氣尚未串接",
      temperature_c: null,
      rain_probability: null,
      precipitation_10min_mm: null,
      wind_speed_mps: null,
      wind_direction_degrees: null,
    },
    uv: { uv_index: null, exposure_level: null },
    air_quality: { aqi: null, status: "無資料" },
    outdoor_comfort: null,
  };
}

async function searchPlaces(params = {}) {
  const query = new URLSearchParams();
  const mappings = {
    q: "q",
    query: "q",
    district: "district",
    category: "category",
    lat: "lat",
    lon: "lon",
    lng: "lon",
    radius_m: "radius_m",
    limit: "limit",
  };

  for (const [sourceKey, targetKey] of Object.entries(mappings)) {
    const value = params[sourceKey];
    if (value !== undefined && value !== null && value !== "") {
      query.set(targetKey, value);
    }
  }
  if (!query.has("limit")) query.set("limit", "20");

  const suffix = query.toString() ? `?${query.toString()}` : "";
  const data = await apiFetch(`/places/search${suffix}`);
  const results = (data.results || []).map(normalizeSearchResult);
  rememberPlaces(results);
  return { count: data.count ?? results.length, results };
}

function normalizeSearchResult(result) {
  const place = result.place || result;
  const categories = Array.isArray(place.categories) ? place.categories.filter(Boolean) : [];
  const category = labelCategory(categories[0]);
  const quality = Number(place.quality_score ?? result.quality_score ?? 0.55);
  const rawScore = Number(result.score ?? quality);
  const score = Math.round(Math.max(0, Math.min(1, rawScore)) * 100);
  const distanceM = result.distance_m ?? place.distance_m;
  const travelTime = estimateTravelMinutes(distanceM, place.district);

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
    description: place.description || "這個地點來自台北景點搜尋平台，目前仍在補齊介紹、營業時間與即時情境資料。",
    rating: place.rating ?? Math.round((3.8 + quality * 1.1) * 10) / 10,
    score,
    matched_travel_time: travelTime,
    travel_time_minutes: travelTime,
    weather_status: inferWeatherStatus(categories),
    weather_summary: "可依現場天氣再確認",
    aqi_status: "moderate",
    aqi_value: "--",
    budget: inferBudget(categories),
    open_now: true,
    route_hint: place.has_coordinates === false ? "位置資料待補，建議開啟地圖確認" : "可用地圖導航確認實際路線",
    reason: buildReason(place, category, travelTime, quality),
    backup_options: [],
    source_score: result.score,
    score_breakdown: result.score_breakdown,
  };
}

function enrichForCriteria(place, criteria) {
  const moodBonus = moodFit(place, criteria.mood);
  const budgetBonus = criteria.budget === "flexible" || place.budget === criteria.budget ? 6 : 0;
  const indoorBonus = criteria.weatherPreference === "indoor" && place.indoor ? 8 : 0;
  const score = Math.max(1, Math.min(100, Math.round(Number(place.score || 55) + moodBonus + budgetBonus + indoorBonus)));
  return {
    ...place,
    score,
    reason: `${place.reason} 這筆推薦已依你的心情、可移動時間與出發區域排序。`,
  };
}

function labelCategory(value) {
  const key = String(value || "景點").trim();
  return CATEGORY_LABELS[key] || key;
}

function estimateTravelMinutes(distanceM, district) {
  if (Number.isFinite(Number(distanceM))) {
    return Math.max(8, Math.round(Number(distanceM) / 420));
  }
  return district ? 24 : 32;
}

function inferWeatherStatus(categories) {
  const text = categories.join(" ");
  if (/博物館|美術館|紀念館|文創|書店|market|museum|gallery/.test(text)) return "suitable";
  if (/公園|河濱|步道|viewpoint/.test(text)) return "watch";
  return "any";
}

function inferBudget(categories) {
  const text = categories.join(" ");
  if (/公園|河濱|古蹟|taipei_featured/.test(text)) return "low";
  if (/餐廳|商圈|restaurant/.test(text)) return "flexible";
  return "medium";
}

function moodFit(place, mood) {
  const text = `${place.name} ${place.category} ${(place.categories || []).join(" ")}`;
  const patterns = {
    relaxing_walk: /公園|河濱|步道|花|山|湖/,
    date: /景觀|文創|餐廳|夜景|藝術|gallery/,
    solo_quiet: /博物館|書店|紀念館|美術館|寺|廟/,
    photo: /景點|古蹟|藝術|景觀|街|山/,
    rainy_backup: /博物館|美術館|紀念館|文創|室內|gallery/,
    night_out: /夜市|商圈|夜景|餐廳|市場/,
  };
  return patterns[mood]?.test(text) ? 10 : 0;
}

function buildReason(place, category, travelTime, quality) {
  const district = place.district ? `位在${place.district}` : "位在臺北市";
  const qualityText = quality >= 0.7 ? "資料完整度高" : "適合作為探索候選";
  return `${place.name}${district}，屬於${category}類型，預估約 ${travelTime} 分鐘可納入行程；${qualityText}。`;
}

function findCachedPlace(id) {
  return placeCache.find((item) => item.id === id) || loadJson(SAVED_KEY, []).find((item) => item.id === id) || null;
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
