/* =========================================================
   NEXT STOPS — preview app logic (vanilla JS, no backend)
   - Hash-based SPA routing: #/, #/results, #/place/:id, #/saved
   - Mock data stands in for /api/recommend and /api/places
   - localStorage simulates /api/saved-places
   ========================================================= */

// --------------------------- Mock data ---------------------------

const MOODS = [
  { id: "relaxing_walk",  label: "Relaxing walk",  emoji: "🌿" },
  { id: "date",           label: "Date",           emoji: "🫶" },
  { id: "solo_quiet",     label: "Solo & quiet",   emoji: "📖" },
  { id: "photo",          label: "Photo hunt",     emoji: "📷" },
  { id: "rainy_backup",   label: "Rainy day",      emoji: "☕" },
  { id: "night_out",      label: "Night outing",   emoji: "🌙" },
];

const PLACES = [
  {
    id: "place_001",
    name: "Dadaocheng Riverside Park",
    category: "Walking · Riverside",
    address: "Datong District, Taipei City",
    rating: 4.5,
    open_now: true,
    travel_time_minutes: 18,
    weather_status: "suitable",
    aqi_status: "good",
    aqi_value: 42,
    weather_summary: "Clear · 24°C · light breeze",
    indoor: false,
    moods: ["relaxing_walk", "solo_quiet", "photo", "date"],
    score: 88,
    description:
      "A calm stretch along the Tamsui River where locals bike, stroll, and wait for the sunset. Golden-hour light is especially good here.",
    reasonTemplate:
      "matches a relaxed mood, sits within ${time} minutes of you, and the evening weather is gentle for walking.",
    backup_options: [
      { name: "ASW Tea House",          category: "Tea & snacks" },
      { name: "Xiahai City God Temple", category: "Quiet landmark" },
      { name: "A Design & Life Project", category: "Boutique shop" },
    ],
  },
  {
    id: "place_002",
    name: "Fujin Street",
    category: "Cafés · Slow street",
    address: "Songshan District, Taipei City",
    rating: 4.6,
    open_now: true,
    travel_time_minutes: 22,
    weather_status: "suitable",
    aqi_status: "moderate",
    aqi_value: 68,
    weather_summary: "Partly cloudy · 23°C",
    indoor: true,
    moods: ["date", "solo_quiet", "photo", "rainy_backup"],
    score: 84,
    description:
      "Tree-lined lanes of independent cafés and small design stores. Low traffic, soft pace — easy to lose an afternoon here.",
    reasonTemplate:
      "fits a slower pace, stays pleasant even if light rain starts, and is easy to reach within ${time} minutes.",
    backup_options: [
      { name: "Fujin Tree 353",       category: "Café" },
      { name: "Minquan Park",         category: "Small park" },
      { name: "Mayu Cafe",            category: "Café" },
    ],
  },
  {
    id: "place_003",
    name: "Huashan 1914 Creative Park",
    category: "Indoor · Galleries & shops",
    address: "Zhongzheng District, Taipei City",
    rating: 4.4,
    open_now: true,
    travel_time_minutes: 14,
    weather_status: "any",
    aqi_status: "moderate",
    aqi_value: 72,
    weather_summary: "Indoor spaces available",
    indoor: true,
    moods: ["rainy_backup", "date", "photo"],
    score: 81,
    description:
      "A converted distillery turned into a warren of galleries, concept stores, and cafés — good for hours of slow browsing on a grey day.",
    reasonTemplate:
      "is mostly indoors, which works well whatever the weather does, and is only ${time} minutes away.",
    backup_options: [
      { name: "Alleycat's Pizza",    category: "Dinner" },
      { name: "VVG Something",       category: "Bookshop" },
      { name: "Legacy Taipei",       category: "Live music" },
    ],
  },
  {
    id: "place_004",
    name: "Xiangshan (Elephant Mountain)",
    category: "Hike · City view",
    address: "Xinyi District, Taipei City",
    rating: 4.7,
    open_now: true,
    travel_time_minutes: 28,
    weather_status: "suitable",
    aqi_status: "good",
    aqi_value: 38,
    weather_summary: "Clear · 22°C at summit",
    indoor: false,
    moods: ["photo", "night_out", "solo_quiet"],
    score: 79,
    description:
      "A short but steep climb up stone steps, rewarded with the classic Taipei 101 skyline view. Popular at dusk.",
    reasonTemplate:
      "has a great skyline view right around dusk, feels doable in your ${time}-minute window, and the air quality is clear tonight.",
    backup_options: [
      { name: "Four Four South Village", category: "Quiet plaza" },
      { name: "Raw Bar by Mume",         category: "Late bite" },
    ],
  },
  {
    id: "place_005",
    name: "Ningxia Night Market",
    category: "Night market · Food",
    address: "Datong District, Taipei City",
    rating: 4.5,
    open_now: true,
    travel_time_minutes: 20,
    weather_status: "any",
    aqi_status: "moderate",
    aqi_value: 75,
    weather_summary: "Mostly covered stalls",
    indoor: false,
    moods: ["night_out", "date", "photo"],
    score: 76,
    description:
      "A compact, food-first night market — easier to navigate than Shilin, with a mix of old-school stalls and newer bites.",
    reasonTemplate:
      "is lively after dark, is a short ${time}-minute trip, and most stalls are covered if it drizzles.",
    backup_options: [
      { name: "Double Chicken Please", category: "Cocktail bar" },
      { name: "Taipei Expo Park",       category: "Quiet walk" },
    ],
  },
];

// --------------------------- State ---------------------------

const state = {
  selectedMood: null,
  time: 120,        // minutes
  distance: 30,     // minutes
  results: [],
  saved: loadSaved(),
};

function loadSaved() {
  try { return JSON.parse(localStorage.getItem("nextstops:saved") || "[]"); }
  catch { return []; }
}
function persistSaved() {
  localStorage.setItem("nextstops:saved", JSON.stringify(state.saved));
  updateSavedCount();
}
function updateSavedCount() {
  const el = document.getElementById("savedCount");
  if (el) el.textContent = state.saved.length;
}
function isSaved(id) { return state.saved.some(p => p.id === id); }

// --------------------------- Recommendation (mock scoring) ---------------------------

function scorePlaces({ mood, time, distance }) {
  const scored = PLACES.map(p => {
    let score = 50; // base
    if (mood && p.moods.includes(mood)) score += 25;
    if (p.travel_time_minutes <= distance) score += 20;
    else score -= 15;
    if (p.travel_time_minutes <= distance * 0.6) score += 5;
    if (p.open_now) score += 10;
    if (p.aqi_status === "good") score += 5;
    if (p.aqi_status === "poor") score -= 15;
    score = Math.max(35, Math.min(98, score));

    const reason = buildReason(p, { mood, time });
    return { ...p, score, reason };
  });
  return scored.sort((a, b) => b.score - a.score).slice(0, 4);
}

function buildReason(place, { mood, time }) {
  const moodLabel = MOODS.find(m => m.id === mood)?.label.toLowerCase();
  const prefix = moodLabel
    ? `This place fits a ${moodLabel} mood — it `
    : "This place ";
  const filled = place.reasonTemplate.replace("${time}", place.travel_time_minutes);
  return prefix + filled;
}

function formatTime(mins) {
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}

// --------------------------- Router ---------------------------

const routes = {
  "/":        renderHome,
  "/results": renderResults,
  "/saved":   renderSaved,
};

function router() {
  const hash = location.hash.replace(/^#/, "") || "/";
  const placeMatch = hash.match(/^\/place\/(.+)$/);

  highlightNav(hash);

  if (placeMatch) {
    renderDetail(placeMatch[1]);
    return;
  }
  const route = routes[hash] || renderHome;
  route();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function highlightNav(hash) {
  document.querySelectorAll(".nav-link").forEach(a => {
    a.classList.toggle("active",
      (a.dataset.nav === "home" && hash === "/") ||
      (a.dataset.nav === "saved" && hash === "/saved"));
  });
}

function go(hash) { location.hash = hash; }

// Delegated navigation: any element with data-nav
document.addEventListener("click", e => {
  const link = e.target.closest("[data-nav]");
  if (!link) return;
  const target = link.dataset.nav;
  if (target === "home") { e.preventDefault(); go("/"); }
  else if (target === "saved") { e.preventDefault(); go("/saved"); }
});

window.addEventListener("hashchange", router);
window.addEventListener("DOMContentLoaded", () => {
  updateSavedCount();
  router();
});

// --------------------------- Rendering ---------------------------

function mount(tplId) {
  const view = document.getElementById("view");
  const tpl = document.getElementById(tplId);
  view.innerHTML = "";
  view.appendChild(tpl.content.cloneNode(true));
}

// ---------- Home ----------

function renderHome() {
  mount("tpl-home");

  // Mood chips
  const grid = document.getElementById("moodGrid");
  MOODS.forEach(m => {
    const btn = document.createElement("button");
    btn.className = "chip" + (state.selectedMood === m.id ? " selected" : "");
    btn.dataset.mood = m.id;
    btn.innerHTML = `<span class="chip-emoji">${m.emoji}</span><span>${m.label}</span>`;
    btn.addEventListener("click", () => {
      state.selectedMood = state.selectedMood === m.id ? null : m.id;
      grid.querySelectorAll(".chip").forEach(c => c.classList.remove("selected"));
      if (state.selectedMood) btn.classList.add("selected");
      updateFindButton();
    });
    grid.appendChild(btn);
  });

  // Sliders
  const timeRange = document.getElementById("timeRange");
  const timeValue = document.getElementById("timeValue");
  const distRange = document.getElementById("distRange");
  const distValue = document.getElementById("distValue");

  timeRange.value = state.time;
  distRange.value = state.distance;
  timeValue.textContent = formatTime(state.time);
  distValue.textContent = `${state.distance} min`;

  timeRange.addEventListener("input", () => {
    state.time = +timeRange.value;
    timeValue.textContent = formatTime(state.time);
  });
  distRange.addEventListener("input", () => {
    state.distance = +distRange.value;
    distValue.textContent = `${state.distance} min`;
  });

  // Presets
  document.querySelectorAll(".preset").forEach(btn => {
    btn.addEventListener("click", () => applyPreset(btn.dataset.preset));
  });

  // CTA
  document.getElementById("findBtn").addEventListener("click", onFind);
  updateFindButton();
}

function updateFindButton() {
  const btn = document.getElementById("findBtn");
  if (!btn) return;
  const enabled = !!state.selectedMood;
  btn.disabled = !enabled;
  btn.firstChild.textContent = enabled
    ? "Find my next stop "
    : "Pick a mood to continue ";
}

function applyPreset(kind) {
  const presets = {
    evening: { mood: "relaxing_walk", time: 90,  distance: 25 },
    date:    { mood: "date",          time: 180, distance: 35 },
    rainy:   { mood: "rainy_backup",  time: 120, distance: 20 },
    solo:    { mood: "solo_quiet",    time: 120, distance: 30 },
  };
  const p = presets[kind];
  if (!p) return;
  state.selectedMood = p.mood;
  state.time = p.time;
  state.distance = p.distance;
  renderHome(); // easiest way to reflect all the changed controls
}

function onFind() {
  if (!state.selectedMood) return;
  state.results = scorePlaces({
    mood: state.selectedMood,
    time: state.time,
    distance: state.distance,
  });
  go("/results");
}

// ---------- Results ----------

function renderResults() {
  if (!state.results.length) {
    // Direct navigation without running — show a friendly fallback using defaults.
    if (!state.selectedMood) state.selectedMood = "relaxing_walk";
    state.results = scorePlaces({
      mood: state.selectedMood,
      time: state.time,
      distance: state.distance,
    });
  }

  mount("tpl-results");

  const moodLabel = MOODS.find(m => m.id === state.selectedMood)?.label.toLowerCase() || "a good outing";
  document.getElementById("resultsSummary").innerHTML =
    `Based on <em>${moodLabel}</em>, <em>${formatTime(state.time)}</em> of time, and up to <em>${state.distance} min</em> away, here are ${state.results.length} places that fit.`;

  const list = document.getElementById("resultsList");
  state.results.forEach((p, i) => list.appendChild(placeCard(p, i + 1)));
}

function placeCard(p, rank) {
  const el = document.createElement("article");
  el.className = "place-card";
  el.innerHTML = `
    <div>
      <div class="place-rank"><span class="dot"></span>Pick ${rank} of ${state.results.length}</div>
      <h3 class="place-name">${p.name}</h3>
      <p class="place-meta">${p.category} · ${p.address.split(",")[0]}</p>
      <div class="badge-row">
        <span class="badge primary">🚇 ${p.travel_time_minutes} min away</span>
        <span class="badge ${p.weather_status === "suitable" ? "ok" : "cool"}">${weatherLabel(p)}</span>
        <span class="badge ${aqiClass(p.aqi_status)}">AQI ${p.aqi_value} · ${p.aqi_status}</span>
        ${p.open_now ? `<span class="badge ok">Open now</span>` : `<span class="badge warn">Closed</span>`}
      </div>
      <p class="place-reason">${p.reason}</p>
    </div>
    <div class="score-dial" style="--score:${p.score}">
      <div class="score-inner">
        <div class="score-value">${p.score}</div>
        <div class="score-label">Fit</div>
      </div>
    </div>
    <div class="card-actions">
      <button class="btn-ghost" data-view="${p.id}">View details</button>
      <button class="btn-primary ${isSaved(p.id) ? "saved" : ""}" data-save="${p.id}">
        ${isSaved(p.id) ? "✓ Saved" : "Save place"}
      </button>
    </div>
  `;

  el.querySelector("[data-view]").addEventListener("click", () => go(`/place/${p.id}`));
  el.querySelector("[data-save]").addEventListener("click", (e) => {
    toggleSave(p);
    const btn = e.currentTarget;
    btn.classList.toggle("saved", isSaved(p.id));
    btn.textContent = isSaved(p.id) ? "✓ Saved" : "Save place";
  });
  return el;
}

function weatherLabel(p) {
  if (p.weather_status === "suitable") return `☀ ${p.weather_summary}`;
  if (p.weather_status === "any")      return `🏠 ${p.weather_summary}`;
  return `☁ ${p.weather_summary}`;
}
function aqiClass(status) {
  if (status === "good")     return "ok";
  if (status === "moderate") return "warn";
  return "warn";
}

// ---------- Detail ----------

function renderDetail(id) {
  const p = PLACES.find(x => x.id === id);
  if (!p) { go("/"); return; }

  mount("tpl-detail");

  // Build a reason even if we arrived directly
  const reason = buildReason(p, { mood: state.selectedMood, time: state.time });

  document.getElementById("detailCategory").textContent = p.category;
  document.getElementById("detailName").textContent = p.name;
  document.getElementById("detailAddress").textContent = p.address;
  document.getElementById("detailReason").textContent = reason;
  document.getElementById("detailDescription").textContent = p.description;
  document.getElementById("mapCaption").textContent = `${p.address} · map preview`;

  // Badges
  const badges = document.getElementById("detailBadges");
  badges.innerHTML = `
    <span class="badge primary">🚇 ${p.travel_time_minutes} min away</span>
    <span class="badge ${p.weather_status === "suitable" ? "ok" : "cool"}">${weatherLabel(p)}</span>
    <span class="badge ${aqiClass(p.aqi_status)}">AQI ${p.aqi_value}</span>
    ${p.open_now ? `<span class="badge ok">Open now</span>` : `<span class="badge warn">Closed</span>`}
  `;

  // Conditions (right now)
  const conditions = document.getElementById("detailConditions");
  conditions.innerHTML = `
    <li><span>Weather</span><span class="kv-val">${p.weather_summary}</span></li>
    <li><span>Air quality</span><span class="kv-val">AQI ${p.aqi_value} (${p.aqi_status})</span></li>
    <li><span>Travel time</span><span class="kv-val">${p.travel_time_minutes} min by transit</span></li>
    <li><span>Status</span><span class="kv-val">${p.open_now ? "Open now" : "Closed"}</span></li>
    <li><span>Rating</span><span class="kv-val">★ ${p.rating.toFixed(1)}</span></li>
  `;

  // Backups
  const backups = document.getElementById("detailBackups");
  backups.innerHTML = "";
  p.backup_options.forEach(b => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="backup-name">${b.name}</span><span class="backup-cat">${b.category}</span>`;
    backups.appendChild(li);
  });

  // Directions link — opens Google Maps search
  const dir = document.getElementById("detailDirections");
  dir.href = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(p.name + " " + p.address)}`;

  // Save button
  const saveBtn = document.getElementById("detailSave");
  const syncSave = () => {
    saveBtn.classList.toggle("saved", isSaved(p.id));
    saveBtn.textContent = isSaved(p.id) ? "✓ Saved" : "Save this place";
  };
  syncSave();
  saveBtn.addEventListener("click", () => { toggleSave(p); syncSave(); });

  // Back button
  document.getElementById("detailBack").addEventListener("click", () => {
    if (state.results.length) go("/results");
    else go("/");
  });
}

// ---------- Saved ----------

function renderSaved() {
  mount("tpl-saved");
  const list = document.getElementById("savedList");

  if (state.saved.length === 0) {
    list.innerHTML = `
      <div class="empty" style="grid-column: 1/-1;">
        <h3>Nothing saved yet</h3>
        <p>When a place looks like a keeper, tap <em>Save</em> — it'll wait for you here.</p>
        <button class="btn-primary" style="margin-top:16px;" data-nav="home">Find a place</button>
      </div>
    `;
    return;
  }

  state.saved.forEach(p => {
    const card = document.createElement("article");
    card.className = "saved-card";
    card.innerHTML = `
      <h3>${p.name}</h3>
      <p class="saved-meta">${p.category} · ${p.address.split(",")[0]}</p>
      <p class="saved-meta" style="color: var(--ink-muted); font-size: 0.82rem;">
        Saved ${new Date(p.created_at).toLocaleDateString()}
      </p>
      <div class="saved-actions">
        <button class="btn-ghost" data-view="${p.id}">View</button>
        <button class="btn-ghost" data-remove="${p.id}">Remove</button>
      </div>
    `;
    card.querySelector("[data-view]").addEventListener("click", () => go(`/place/${p.id}`));
    card.querySelector("[data-remove]").addEventListener("click", () => {
      state.saved = state.saved.filter(s => s.id !== p.id);
      persistSaved();
      renderSaved();
      toast("Removed from saved");
    });
    list.appendChild(card);
  });
}

// --------------------------- Actions ---------------------------

function toggleSave(p) {
  if (isSaved(p.id)) {
    state.saved = state.saved.filter(s => s.id !== p.id);
    toast("Removed from saved");
  } else {
    state.saved.unshift({
      id: p.id,
      name: p.name,
      category: p.category,
      address: p.address,
      lat: p.lat,
      lng: p.lng,
      created_at: new Date().toISOString(),
    });
    toast("Saved for later");
  }
  persistSaved();
}

let toastTimer;
function toast(msg) {
  let el = document.querySelector(".toast");
  if (!el) {
    el = document.createElement("div");
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 1800);
}
