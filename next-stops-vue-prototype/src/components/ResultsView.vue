<script setup>
import IconGlyph from "./IconGlyph.vue";
import { LOCATION_FALLBACK_LABEL, MOODS } from "../constants";
import { aqiChip, budgetLabel, commuteParts, suitabilityLabel, weatherChips } from "../utils/formatters";

defineProps({
  criteria: { type: Object, required: true },
  results: { type: Array, required: true },
  savedIds: { type: Array, required: true },
  feedbackByPlace: { type: Object, default: () => ({}) },
  loading: { type: Boolean, default: false },
  error: { type: String, default: "" },
});
const emit = defineEmits(["navigate", "view", "toggle-save", "find", "feedback"]);

const FEEDBACK_OPTIONS = [
  { type: "good_fit", label: "Good fit" },
  { type: "too_far", label: "Too far" },
  { type: "not_my_vibe", label: "Not my vibe" },
  { type: "prefer_indoor", label: "More indoor" },
];

function commuteInfo(place) {
  return commuteParts(place.commute, place.matched_travel_time ?? place.travel_time_minutes);
}

function placeWeatherChips(place) {
  return weatherChips(place.context, place.weather_summary).slice(0, 3);
}

function placeAqiChip(place) {
  return aqiChip(place.context, place.aqi_value, place.aqi_status);
}
</script>

<template>
  <main class="screen results-screen">
    <header class="screen-header">
      <button class="back-button" type="button" @click="emit('navigate', '/')">‹</button>
      <div>
        <p class="muted">{{ criteria.locationLabel || LOCATION_FALLBACK_LABEL }} 出發</p>
        <h1>{{ MOODS.find((item) => item.id === criteria.mood)?.label || "推薦" }}</h1>
      </div>
    </header>

    <section v-if="loading && !results.length" class="loading-state" aria-live="polite">
      <div class="loading-visual" aria-hidden="true">
        <div class="loader-calm">
          <span class="calm-ring one"></span>
          <span class="calm-ring two"></span>
          <span class="calm-dot main"></span>
          <span class="calm-dot drift"></span>
          <span class="calm-path"></span>
        </div>
        <div class="route-preview">
          <span class="route-thread"></span>
          <i class="node start"></i>
          <i class="node mid"></i>
          <i class="node end"></i>
        </div>
        <div class="loading-card-stack">
          <span></span>
          <span></span>
          <span></span>
        </div>
      </div>
      <h2>正在規劃下一站</h2>
      <p>
        已送出 {{ MOODS.find((item) => item.id === criteria.mood)?.label || "目前心情" }}、
        {{ criteria.locationLabel || LOCATION_FALLBACK_LABEL }}、{{ criteria.distance }} 分鐘移動範圍。
      </p>
      <div class="loading-steps">
        <span>定位</span>
        <span>景點搜尋</span>
        <span>通勤比較</span>
        <span>推薦排序</span>
      </div>
    </section>

    <section v-else-if="results.length" class="result-list">
      <article v-for="(place, index) in results" :key="place.id" class="place-card">
        <button class="place-main" type="button" @click="emit('view', place.id)">
          <span class="rank">0{{ index + 1 }}</span>
          <div>
            <h2>{{ place.name }}</h2>
            <p>{{ place.category }} / {{ place.address }}</p>
          </div>
        </button>
        <div class="badge-row">
          <span class="badge-chip suitability-chip">
            <IconGlyph name="spark" />
            <strong>{{ suitabilityLabel(place) }}</strong>
          </span>
          <span class="badge-chip commute-badge">
            <IconGlyph :name="commuteInfo(place).icon" />
            <strong>{{ commuteInfo(place).duration }}</strong>
          </span>
          <span
            v-for="item in placeWeatherChips(place)"
            :key="`${place.id}-${item.key}`"
            class="badge-chip weather-chip"
            :class="item.className"
          >
            <IconGlyph :name="item.icon" />
            <strong>{{ item.label }}</strong>
          </span>
          <span class="badge-chip aqi-chip" :class="placeAqiChip(place).className">
            <IconGlyph :name="placeAqiChip(place).icon" />
            <strong>{{ placeAqiChip(place).label }}</strong>
            <small>{{ placeAqiChip(place).detail }}</small>
          </span>
          <span>{{ budgetLabel(place.budget) }}</span>
        </div>
        <div class="feedback-row" aria-label="推薦回饋">
          <button
            v-for="option in FEEDBACK_OPTIONS"
            :key="option.type"
            class="feedback-chip"
            :class="{ selected: feedbackByPlace[place.id] === option.type }"
            type="button"
            @click="emit('feedback', place.id, option.type)"
          >
            {{ option.label }}
          </button>
        </div>
        <div class="card-footer">
          <button class="ghost-action" :class="{ saved: savedIds.includes(place.id) }" type="button" @click="emit('toggle-save', place)">
            {{ savedIds.includes(place.id) ? "Saved" : "Save" }}
          </button>
        </div>
      </article>
    </section>

    <section v-else-if="error" class="empty-state error-state">
      <h2>推薦沒有完成</h2>
      <p>後端回報錯誤，請先看下面的錯誤訊息。</p>
      <pre>{{ error }}</pre>
      <button class="primary-action" type="button" @click="emit('find')">Retry recommendation</button>
      <button class="ghost-action empty-secondary" type="button" @click="emit('navigate', '/')">Edit settings</button>
    </section>

    <section v-else class="empty-state">
      <h2>目前沒有推薦結果</h2>
      <p>目前心情是 {{ MOODS.find((item) => item.id === criteria.mood)?.label || "未設定" }}。可以直接重新產生推薦，或回首頁調整設定。</p>
      <button class="primary-action" type="button" @click="emit('find')">Generate recommendations</button>
      <button class="ghost-action empty-secondary" type="button" @click="emit('navigate', '/')">Edit settings</button>
    </section>
  </main>
</template>
