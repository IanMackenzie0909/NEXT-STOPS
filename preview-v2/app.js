const STORAGE_KEY = "nextstops:v2";
const SCORE_VERSION = 2;

const MOODS = [
  { id: "reset", label: "Reset my head", hint: "quiet, low pressure" },
  { id: "date", label: "Easy date", hint: "warm, memorable" },
  { id: "wander", label: "Wander and look", hint: "scenic, open-ended" },
  { id: "rain", label: "Rain backup", hint: "indoor, reliable" },
  { id: "social", label: "Small hangout", hint: "food, easy talk" },
  { id: "focus", label: "Solo recharge", hint: "calm, not crowded" },
];

const PROFILE_SLIDERS = [
  { id: "quiet", label: "Quiet over lively", left: "Lively", right: "Quiet" },
  { id: "travel", label: "Sensitive to travel time", left: "Flexible", right: "Close only" },
  { id: "budget", label: "Sensitive to price", left: "Flexible", right: "Careful" },
  { id: "indoor", label: "Indoor comfort", left: "Outdoor OK", right: "Indoor" },
  { id: "scenery", label: "Scenery matters", left: "Not much", right: "A lot" },
  { id: "food", label: "Food matters", left: "Not much", right: "A lot" },
  { id: "crowd", label: "Avoid crowded places", left: "Crowds OK", right: "Avoid" },
];

const LOCATION_LABELS = {
  taipei_main: "Taipei Main Station",
  xinyi: "Xinyi District",
  daan: "Da'an Park",
  songshan: "Songshan",
};

const PLACES = [
  {
    id: "riverside",
    name: "Dadaocheng Riverside Park",
    category: "Riverside walk",
    address: "Datong District, Taipei",
    description: "Open riverside space for walking, sunset watching, and quiet decompression after a busy day.",
    moods: ["reset", "wander", "focus", "date"],
    travel: { taipei_main: 18, xinyi: 30, daan: 24, songshan: 28 },
    price: 1,
    indoor: 0,
    quiet: 0.72,
    scenery: 0.9,
    food: 0.45,
    crowd: 0.42,
    weather: "outdoor",
    aqi: "good",
    route: "Transit to Beimen or Daqiaotou, then a relaxed walk toward the river.",
    backup: ["ASW Tea House", "Dihua Street shops"],
  },
  {
    id: "fujin",
    name: "Fujin Street",
    category: "Cafes and slow street",
    address: "Songshan District, Taipei",
    description: "Tree-lined lanes with cafes, small shops, and a softer pace than the central shopping areas.",
    moods: ["date", "focus", "rain", "social"],
    travel: { taipei_main: 23, xinyi: 14, daan: 20, songshan: 10 },
    price: 2,
    indoor: 0.8,
    quiet: 0.68,
    scenery: 0.58,
    food: 0.82,
    crowd: 0.38,
    weather: "mixed",
    aqi: "moderate",
    route: "MRT or bus to Minsheng community, then a short walk through calm side streets.",
    backup: ["Fujin Tree 353", "Mayu Cafe"],
  },
  {
    id: "huashan",
    name: "Huashan 1914 Creative Park",
    category: "Galleries and shops",
    address: "Zhongzheng District, Taipei",
    description: "Indoor and semi-indoor cultural spaces with exhibitions, shops, cafes, and easy backup choices.",
    moods: ["rain", "date", "wander", "social"],
    travel: { taipei_main: 12, xinyi: 18, daan: 10, songshan: 18 },
    price: 2,
    indoor: 0.72,
    quiet: 0.45,
    scenery: 0.62,
    food: 0.7,
    crowd: 0.7,
    weather: "indoor",
    aqi: "moderate",
    route: "Direct transit to Zhongxiao Xinsheng, then a very short walk.",
    backup: ["VVG Something", "Legacy Taipei"],
  },
  {
    id: "xiangshan",
    name: "Xiangshan Trail",
    category: "Short hike and skyline",
    address: "Xinyi District, Taipei",
    description: "A steep but short climb with a strong skyline payoff, best when weather and energy are both good.",
    moods: ["wander", "reset"],
    travel: { taipei_main: 28, xinyi: 12, daan: 20, songshan: 24 },
    price: 1,
    indoor: 0,
    quiet: 0.5,
    scenery: 0.98,
    food: 0.2,
    crowd: 0.78,
    weather: "outdoor",
    aqi: "good",
    route: "MRT to Xiangshan, followed by stairs. Short distance, high effort.",
    backup: ["Four Four South Village", "Taipei 101 area"],
  },
  {
    id: "ningxia",
    name: "Ningxia Night Market",
    category: "Food street",
    address: "Datong District, Taipei",
    description: "Compact food-first night market with plenty of snack choices and a lively but manageable route.",
    moods: ["social", "date"],
    travel: { taipei_main: 16, xinyi: 30, daan: 22, songshan: 26 },
    price: 1,
    indoor: 0.25,
    quiet: 0.15,
    scenery: 0.35,
    food: 0.95,
    crowd: 0.82,
    weather: "mixed",
    aqi: "moderate",
    route: "Transit to Shuanglian or Zhongshan, then a short food-stall walk.",
    backup: ["Taipei Expo Park", "Dihua Street"],
  },
  {
    id: "beitou",
    name: "Beitou Library and Hot Spring Park",
    category: "Green quiet zone",
    address: "Beitou District, Taipei",
    description: "A slower green area with library architecture, thermal valley walks, and quiet corners.",
    moods: ["focus", "reset", "wander"],
    travel: { taipei_main: 36, xinyi: 48, daan: 42, songshan: 46 },
    price: 1,
    indoor: 0.45,
    quiet: 0.86,
    scenery: 0.82,
    food: 0.35,
    crowd: 0.36,
    weather: "mixed",
    aqi: "good",
    route: "MRT to Xinbeitou. Longer ride, but low pressure after arrival.",
    backup: ["Beitou Hot Spring Museum", "Thermal Valley"],
  },
];

const DEFAULT_STATE = {
  route: "home",
  selectedMood: "reset",
  context: {
    location: "taipei_main",
    weather: "any",
    budget: "medium",
    time: 120,
    distance: 35,
    company: "solo",
  },
  profile: {
    quiet: 65,
    travel: 55,
    budget: 50,
    indoor: 45,
    scenery: 60,
    food: 45,
    crowd: 60,
  },
  feedback: [],
  saved: [],
  results: [],
  selectedPlaceId: null,
  scoreVersion: SCORE_VERSION,
};

let state = loadState();

window.addEventListener("DOMContentLoaded", () => {
  document.body.addEventListener("click", handleDocumentClick);
  window.addEventListener("hashchange", routeFromHash);
  routeFromHash();
});

function loadState() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    return {
      ...structuredClone(DEFAULT_STATE),
      ...stored,
      context: { ...DEFAULT_STATE.context, ...(stored.context || {}) },
      profile: { ...DEFAULT_STATE.profile, ...(stored.profile || {}) },
      feedback: stored.feedback || [],
      saved: stored.saved || [],
      results: stored.scoreVersion === SCORE_VERSION ? stored.results || [] : [],
      scoreVersion: SCORE_VERSION,
    };
  } catch {
    return structuredClone(DEFAULT_STATE);
  }
}

function persist() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  updateSavedCount();
}

function routeFromHash() {
  const route = location.hash.replace("#", "") || "home";
  if (route.startsWith("detail/")) {
    state.route = "detail";
    state.selectedPlaceId = route.split("/")[1];
  } else if (["home", "results", "saved"].includes(route)) {
    state.route = route;
  } else {
    state.route = "home";
  }
  render();
}

function go(route) {
  location.hash = route;
}

function render() {
  updateSavedCount();
  setActiveNav();

  if (state.route === "results" && state.results.length === 0) {
    state.results = scorePlaces();
  }

  if (state.route === "home") renderHome();
  if (state.route === "results") renderResults();
  if (state.route === "detail") renderDetail();
  if (state.route === "saved") renderSaved();
}

function mount(templateId) {
  const app = document.getElementById("app");
  const template = document.getElementById(templateId);
  app.innerHTML = "";
  app.appendChild(template.content.cloneNode(true));
}

function renderHome() {
  mount("tpl-home");
  renderProfileSnapshot();
  renderProfileSliders();
  renderMoodChoices();
  bindContextInputs();

  document.getElementById("resetProfile").addEventListener("click", () => {
    state.profile = { ...DEFAULT_STATE.profile };
    state.feedback = [];
    persist();
    renderHome();
    toast("Profile reset for this test");
  });

  document.getElementById("searchForm").addEventListener("submit", (event) => {
    event.preventDefault();
    state.results = scorePlaces();
    persist();
    go("results");
  });
}

function renderProfileSnapshot() {
  const el = document.getElementById("profileSnapshot");
  const top = strongestProfileSignals(3);
  el.innerHTML = `
    <p class="eyebrow">Your current weighting</p>
    <h2>${top.map((item) => item.label).join(", ")}</h2>
    <p>These are not permanent traits. They are test weights you can adjust or override with feedback.</p>
  `;
}

function strongestProfileSignals(count) {
  return PROFILE_SLIDERS
    .map((item) => ({ ...item, value: state.profile[item.id] }))
    .sort((a, b) => b.value - a.value)
    .slice(0, count);
}

function renderProfileSliders() {
  const host = document.getElementById("profileSliders");
  host.innerHTML = PROFILE_SLIDERS.map((item) => `
    <label class="pref-slider">
      <span>
        <strong>${item.label}</strong>
        <em>${state.profile[item.id]}%</em>
      </span>
      <input type="range" min="0" max="100" value="${state.profile[item.id]}" data-profile="${item.id}" />
      <small>${item.left}<b>${item.right}</b></small>
    </label>
  `).join("");

  host.querySelectorAll("[data-profile]").forEach((input) => {
    input.addEventListener("input", () => {
      state.profile[input.dataset.profile] = Number(input.value);
      persist();
      renderProfileSliders();
      renderProfileSnapshot();
    });
  });
}

function renderMoodChoices() {
  const host = document.getElementById("moodChoices");
  host.innerHTML = MOODS.map((mood) => `
    <button type="button" class="choice ${state.selectedMood === mood.id ? "selected" : ""}" data-mood="${mood.id}">
      <strong>${mood.label}</strong>
      <span>${mood.hint}</span>
    </button>
  `).join("");

  host.querySelectorAll("[data-mood]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedMood = button.dataset.mood;
      persist();
      renderMoodChoices();
    });
  });
}

function bindContextInputs() {
  const mapping = {
    locationInput: "location",
    weatherInput: "weather",
    budgetInput: "budget",
    timeInput: "time",
    distanceInput: "distance",
    companyInput: "company",
  };

  Object.entries(mapping).forEach(([id, key]) => {
    const input = document.getElementById(id);
    input.value = state.context[key];
    input.addEventListener("change", () => {
      const numeric = ["time", "distance"].includes(key);
      state.context[key] = numeric ? Number(input.value) : input.value;
      persist();
    });
  });
}

function scorePlaces() {
  return PLACES.map((place) => {
    const breakdown = buildBreakdown(place);
    const score = calculateScore(breakdown);
    return {
      id: place.id,
      score,
      confidence: confidenceLabel(),
      breakdown,
      reason: buildReason(place, breakdown),
    };
  }).sort((a, b) => b.score - a.score).slice(0, 5);
}

function buildBreakdown(place) {
  const profile = state.profile;
  const context = state.context;
  const travel = place.travel[context.location];
  const moodFit = place.moods.includes(state.selectedMood) ? 1 : 0.25;
  const travelFit = travelFitFor(travel, context.distance);
  const budgetFit = budgetFitFor(place);
  const weatherFit = weatherFitFor(place);
  const companyFit = companyFitFor(place);

  return [
    weighted("Current mood", moodFit, 22, "matches the selected need"),
    weighted("Travel effort", travelFit, weightFrom(profile.travel, 10, 25), `${travel} min from ${LOCATION_LABELS[context.location]}`),
    weighted("Budget comfort", budgetFit, weightFrom(profile.budget, 6, 18), priceCopy(place.price)),
    weighted("Weather comfort", weatherFit, weightFrom(profile.indoor, 8, 18), weatherCopy(place)),
    weighted("Quiet fit", place.quiet, weightFrom(profile.quiet, 5, 18), quietCopy(place.quiet)),
    weighted("Crowd comfort", 1 - place.crowd, weightFrom(profile.crowd, 5, 18), crowdCopy(place.crowd)),
    weighted("Scenery value", place.scenery, weightFrom(profile.scenery, 4, 16), "visual payoff"),
    weighted("Food value", place.food, weightFrom(profile.food, 4, 16), "food or cafe support"),
    weighted("Social fit", companyFit, 10, `${context.company} context`),
    feedbackAdjustment(place),
  ];
}

function weighted(label, fit, weight, note) {
  return {
    label,
    points: Math.round(fit * weight),
    fit,
    weight,
    note,
  };
}

function calculateScore(breakdown) {
  const scoredSignals = breakdown.filter((item) => item.label !== "Your feedback");
  const feedback = breakdown.find((item) => item.label === "Your feedback")?.points || 0;
  const earned = scoredSignals.reduce((sum, item) => sum + item.points, 0);
  const possible = scoredSignals.reduce((sum, item) => sum + item.weight, 0);
  const normalizedFit = possible ? earned / possible : 0;
  const score = 28 + normalizedFit * 68 + feedback;
  return Math.round(Math.max(18, Math.min(96, score)));
}

function feedbackAdjustment(place) {
  const relevant = state.feedback.filter((item) => item.placeId === place.id);
  const points = relevant.reduce((sum, item) => sum + feedbackPoints(item.type), 0);
  return {
    label: "Your feedback",
    points,
    fit: points > 0 ? 1 : points < 0 ? 0 : 0.5,
    weight: Math.abs(points),
    note: relevant.length ? `${relevant.length} signal(s)` : "no signals yet",
  };
}

function feedbackPoints(type) {
  const map = {
    good_fit: 8,
    too_far: -7,
    too_crowded: -6,
    too_expensive: -6,
    not_my_vibe: -8,
    quieter: 3,
    indoor: 3,
    scenic: 3,
  };
  return map[type] || 0;
}

function budgetFitFor(place) {
  if (state.context.budget === "flexible") return 0.9;
  if (state.context.budget === "medium") return place.price <= 2 ? 0.92 : 0.55;
  return place.price === 1 ? 1 : 0.45;
}

function weatherFitFor(place) {
  if (state.context.weather === "any") return place.weather === "outdoor" ? 0.75 : 0.95;
  if (state.context.weather === "indoor") return place.indoor;
  if (state.context.weather === "avoid_rain") return place.weather === "indoor" ? 1 : place.weather === "mixed" ? 0.75 : 0.35;
  return 0.7;
}

function travelFitFor(travel, limit) {
  if (travel <= limit) {
    return clamp01(1 - (travel / limit) * 0.35);
  }
  return clamp01(0.65 - (travel - limit) / 35);
}

function companyFitFor(place) {
  if (state.context.company === "solo") return (place.quiet + (1 - place.crowd)) / 2;
  if (state.context.company === "date") return (place.scenery + place.food + place.quiet) / 3;
  return (place.food + (1 - Math.abs(place.crowd - 0.55))) / 2;
}

function weightFrom(value, min, max) {
  return min + ((max - min) * value) / 100;
}

function clamp01(value) {
  return Math.max(0, Math.min(1, value));
}

function renderResults() {
  mount("tpl-results");
  const mood = MOODS.find((item) => item.id === state.selectedMood);
  document.getElementById("resultsTitle").textContent = `${state.results.length} places for ${mood.label.toLowerCase()}`;
  document.getElementById("resultsCopy").textContent =
    "These are fit estimates, not universal truth. Use the feedback buttons to tune the next round.";

  renderLearningSummary();

  const host = document.getElementById("resultList");
  host.innerHTML = state.results.map((result, index) => resultCard(result, index)).join("");
  host.querySelectorAll("[data-detail]").forEach((button) => {
    button.addEventListener("click", () => go(`detail/${button.dataset.detail}`));
  });
  host.querySelectorAll("[data-save]").forEach((button) => {
    button.addEventListener("click", () => toggleSave(button.dataset.save));
  });
  host.querySelectorAll("[data-feedback]").forEach((button) => {
    button.addEventListener("click", () => addFeedback(button.dataset.place, button.dataset.feedback));
  });
}

function renderLearningSummary() {
  const host = document.getElementById("learningSummary");
  const strongest = strongestProfileSignals(4);
  host.innerHTML = `
    <div class="signal-list">
      ${strongest.map((item) => `<span>${item.label}: ${item.value}%</span>`).join("")}
    </div>
    <p>${state.feedback.length} feedback signal(s) recorded in this browser.</p>
  `;
}

function resultCard(result, index) {
  const place = placeById(result.id);
  const topBreakdown = result.breakdown
    .filter((item) => item.points > 0)
    .sort((a, b) => b.points - a.points)
    .slice(0, 3);
  const saved = isSaved(place.id);

  return `
    <article class="result-card">
      <div class="score-block">
        <span>${result.score}</span>
        <small>${result.confidence}</small>
      </div>
      <div class="result-main">
        <p class="rank">Option ${index + 1}</p>
        <h2>${place.name}</h2>
        <p class="meta">${place.category} / ${place.address} / ${place.travel[state.context.location]} min estimate</p>
        <p class="reason">${result.reason}</p>
        <div class="breakdown">
          ${topBreakdown.map((item) => `<span>${item.label} +${item.points}</span>`).join("")}
        </div>
        <div class="feedback-row" aria-label="Recommendation feedback">
          ${feedbackButton(place.id, "good_fit", "Good fit")}
          ${feedbackButton(place.id, "too_far", "Too far")}
          ${feedbackButton(place.id, "too_crowded", "Too crowded")}
          ${feedbackButton(place.id, "too_expensive", "Too pricey")}
          ${feedbackButton(place.id, "not_my_vibe", "Not my vibe")}
        </div>
        <div class="card-actions">
          <button class="ghost-button" data-detail="${place.id}">Details</button>
          <button class="primary-button slim" data-save="${place.id}">${saved ? "Saved" : "Save"}</button>
        </div>
      </div>
    </article>
  `;
}

function feedbackButton(placeId, type, label) {
  return `<button type="button" data-place="${placeId}" data-feedback="${type}">${label}</button>`;
}

function addFeedback(placeId, type) {
  state.feedback.push({ placeId, type, createdAt: new Date().toISOString() });
  tuneProfile(type);
  state.results = scorePlaces();
  persist();
  renderResults();
  toast("Feedback recorded. Scores retuned.");
}

function tuneProfile(type) {
  const changes = {
    too_far: { travel: 6 },
    too_crowded: { crowd: 7, quiet: 4 },
    too_expensive: { budget: 7 },
    not_my_vibe: { quiet: 2, scenery: 2 },
    quieter: { quiet: 5, crowd: 5 },
    indoor: { indoor: 6 },
    scenic: { scenery: 6 },
    good_fit: {},
  }[type] || {};

  Object.entries(changes).forEach(([key, delta]) => {
    state.profile[key] = Math.max(0, Math.min(100, state.profile[key] + delta));
  });
}

function renderDetail() {
  mount("tpl-detail");
  const place = placeById(state.selectedPlaceId) || placeById(state.results[0]?.id) || PLACES[0];
  const result = state.results.find((item) => item.id === place.id) || scoreSingle(place);
  const shell = document.getElementById("detailShell");
  shell.innerHTML = `
    <div class="detail-hero">
      <div>
        <p class="eyebrow">${place.category}</p>
        <h1>${place.name}</h1>
        <p>${place.description}</p>
        <div class="detail-actions">
          <button class="primary-button slim" data-save="${place.id}">${isSaved(place.id) ? "Saved" : "Save this place"}</button>
          <button class="ghost-button" data-feedback="good_fit" data-place="${place.id}">Good fit</button>
          <button class="ghost-button" data-feedback="not_my_vibe" data-place="${place.id}">Not my vibe</button>
        </div>
      </div>
      <div class="map-preview" aria-label="Map preview">
        <span>${place.travel[state.context.location]} min estimate</span>
      </div>
    </div>

    <div class="detail-grid">
      <section class="panel">
        <h2>Why this estimate exists</h2>
        <p>${result.reason}</p>
        <div class="full-breakdown">
          ${result.breakdown.map((item) => `
            <div>
              <span>${item.label}</span>
              <strong>${item.points >= 0 ? "+" : ""}${item.points}</strong>
              <small>${item.note}</small>
            </div>
          `).join("")}
        </div>
      </section>
      <section class="panel">
        <h2>Route and context</h2>
        <ul class="plain-list">
          <li><span>Start</span><strong>${LOCATION_LABELS[state.context.location]}</strong></li>
          <li><span>Travel</span><strong>${place.travel[state.context.location]} min estimate</strong></li>
          <li><span>Route feel</span><strong>${place.route}</strong></li>
          <li><span>Backups</span><strong>${place.backup.join(", ")}</strong></li>
        </ul>
      </section>
    </div>
  `;

  shell.querySelectorAll("[data-save]").forEach((button) => {
    button.addEventListener("click", () => toggleSave(button.dataset.save));
  });
  shell.querySelectorAll("[data-feedback]").forEach((button) => {
    button.addEventListener("click", () => addFeedback(button.dataset.place, button.dataset.feedback));
  });
}

function renderSaved() {
  mount("tpl-saved");
  const host = document.getElementById("savedGrid");
  if (state.saved.length === 0) {
    host.innerHTML = `
      <div class="empty-state">
        <h2>No saved places yet</h2>
        <p>Save a result to test notes and the saved-place flow.</p>
        <button class="primary-button slim" data-route="results">See results</button>
      </div>
    `;
    return;
  }

  host.innerHTML = state.saved.map((saved) => {
    const place = placeById(saved.id);
    return `
      <article class="saved-card">
        <h2>${place.name}</h2>
        <p>${place.category} / saved ${new Date(saved.createdAt).toLocaleDateString()}</p>
        <textarea data-note="${place.id}" placeholder="Add a note for later">${saved.note || ""}</textarea>
        <div class="card-actions">
          <button class="ghost-button" data-detail="${place.id}">Details</button>
          <button class="ghost-button danger" data-remove="${place.id}">Remove</button>
        </div>
      </article>
    `;
  }).join("");

  host.querySelectorAll("[data-note]").forEach((textarea) => {
    textarea.addEventListener("input", () => {
      state.saved = state.saved.map((item) => item.id === textarea.dataset.note ? { ...item, note: textarea.value } : item);
      persist();
    });
  });
  host.querySelectorAll("[data-detail]").forEach((button) => {
    button.addEventListener("click", () => go(`detail/${button.dataset.detail}`));
  });
  host.querySelectorAll("[data-remove]").forEach((button) => {
    button.addEventListener("click", () => {
      state.saved = state.saved.filter((item) => item.id !== button.dataset.remove);
      persist();
      renderSaved();
      toast("Removed from saved");
    });
  });
}

function scoreSingle(place) {
  const breakdown = buildBreakdown(place);
  return {
    id: place.id,
    score: calculateScore(breakdown),
    confidence: confidenceLabel(),
    breakdown,
    reason: buildReason(place, breakdown),
  };
}

function buildReason(place, breakdown) {
  const top = breakdown
    .filter((item) => item.points > 0)
    .sort((a, b) => b.points - a.points)
    .slice(0, 2)
    .map((item) => item.label.toLowerCase());
  return `Initial fit estimate: ${place.name} ranks well for ${top.join(" and ")}. Correct it if that does not match your real feeling.`;
}

function confidenceLabel() {
  if (state.feedback.length >= 8) return "learned fit";
  if (state.feedback.length >= 3) return "tuned fit";
  return "initial estimate";
}

function toggleSave(placeId) {
  if (isSaved(placeId)) {
    state.saved = state.saved.filter((item) => item.id !== placeId);
    toast("Removed from saved");
  } else {
    state.saved.unshift({ id: placeId, note: "", createdAt: new Date().toISOString() });
    toast("Saved for later");
  }
  persist();
  render();
}

function isSaved(placeId) {
  return state.saved.some((item) => item.id === placeId);
}

function placeById(id) {
  return PLACES.find((place) => place.id === id);
}

function handleDocumentClick(event) {
  const routeButton = event.target.closest("[data-route]");
  if (!routeButton) return;
  event.preventDefault();
  go(routeButton.dataset.route);
}

function setActiveNav() {
  document.querySelectorAll(".top-nav a").forEach((link) => {
    link.classList.toggle("active", link.dataset.route === state.route);
  });
}

function updateSavedCount() {
  const el = document.getElementById("savedCount");
  if (el) el.textContent = state.saved.length;
}

function priceCopy(price) {
  if (price === 1) return "low spend";
  if (price === 2) return "medium spend";
  return "higher spend";
}

function weatherCopy(place) {
  if (place.weather === "indoor") return "safe in bad weather";
  if (place.weather === "mixed") return "has backup cover";
  return "best with decent weather";
}

function quietCopy(value) {
  if (value > 0.7) return "quiet leaning";
  if (value > 0.45) return "moderate noise";
  return "lively";
}

function crowdCopy(value) {
  if (value > 0.7) return "can feel crowded";
  if (value > 0.45) return "medium crowd";
  return "usually manageable";
}

function toast(message) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.add("show");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => el.classList.remove("show"), 1800);
}
