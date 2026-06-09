<script setup>
import { computed, ref } from "vue";
import AppIcon from "./AppIcon.vue";
import TransportIcon from "./TransportIcon.vue";
import { BUDGET_LABELS, LOCATION_FALLBACK_LABEL, MOODS, TRANSPORT_MODES, WEATHER_LABELS } from "../constants";
import { formatTime } from "../utils/formatters";

const props = defineProps({
  criteria: { type: Object, required: true },
  loading: { type: Boolean, default: false },
  locating: { type: Boolean, default: false },
  savedCount: { type: Number, default: 0 },
  favoriteStarts: { type: Array, default: () => [] },
  user: { type: Object, default: null },
});
const emit = defineEmits(["update:criteria", "find", "locate", "use-favorite-start", "navigate"]);
const openSelect = ref("");

const locationText = computed(() => {
  if (props.criteria.locationSource === "gps" && props.criteria.lat && props.criteria.lon) {
    return "定位 • 你的位置";
  }
  if (props.criteria.locationSource === "favorite") {
    return `定位 • ${props.criteria.locationLabel || "已儲存起點"}`;
  }
  return `定位 • ${props.criteria.locationLabel || LOCATION_FALLBACK_LABEL}`;
});

const locationSubtext = computed(() => {
  if (props.criteria.locationSource === "gps" && props.criteria.lat && props.criteria.lon) {
    return `(${Number(props.criteria.lat).toFixed(4)}, ${Number(props.criteria.lon).toFixed(4)})`;
  }
  if (props.criteria.locationSource === "favorite" && props.criteria.lat && props.criteria.lon) {
    return `(${Number(props.criteria.lat).toFixed(4)}, ${Number(props.criteria.lon).toFixed(4)})`;
  }
  return "目前使用預設起點；按 Use location 可改用即時定位。";
});

const canUseFallback = computed(() => props.criteria.locationSource !== "fallback");
const greeting = computed(() => {
  const hour = new Date().getHours();
  if (hour >= 5 && hour < 12) return "Good morning";
  if (hour >= 12 && hour < 18) return "Good afternoon";
  if (hour >= 18 && hour < 23) return "Good evening";
  return "Good night";
});
const userName = computed(() => props.user?.name || props.user?.account || "Guest");

function patch(updates) {
  emit("update:criteria", updates);
}

function chooseSelect(updates) {
  patch(updates);
  openSelect.value = "";
}

function toggleTransport(modeId) {
  const current = Array.isArray(props.criteria.transportModes) ? props.criteria.transportModes : [];
  patch({
    transportModes: current.includes(modeId)
      ? current.filter((item) => item !== modeId)
      : [...current, modeId],
  });
}

function useFallbackLocation() {
  patch({
    location: "taipei_main",
    locationLabel: LOCATION_FALLBACK_LABEL,
    locationSource: "fallback",
    lat: null,
    lon: null,
  });
}
</script>

<template>
  <main class="screen home-screen">
    <header class="home-header">
      <div>
        <p class="muted greeting-line">
          <span>{{ greeting }}</span>
          <b>{{ userName }}</b>
        </p>
        <h1>Where to next?</h1>
      </div>
    </header>

    <section class="choice-panel">
      <div class="panel-head">
        <AppIcon />
        <div>
          <h2>Find a calm stop nearby</h2>
          <p>用少量訊號讓推薦足夠可用。</p>
        </div>
      </div>

      <div class="mood-grid">
        <button
          v-for="mood in MOODS"
          :key="mood.id"
          class="mood-chip"
          :class="{ selected: criteria.mood === mood.id }"
          type="button"
          @click="patch({ mood: mood.id })"
        >
          <strong>{{ mood.short }}</strong>
          <span>{{ mood.label }}</span>
        </button>
      </div>

      <label class="range-field">
        <span>可安排時間 <strong>{{ formatTime(criteria.time) }}</strong></span>
        <input type="range" min="30" max="300" step="15" :value="criteria.time" @input="patch({ time: Number($event.target.value) })" />
      </label>

      <label class="range-field">
        <span>最多移動 <strong>{{ criteria.distance }} 分鐘</strong></span>
        <input type="range" min="10" max="90" step="5" :value="criteria.distance" @input="patch({ distance: Number($event.target.value) })" />
      </label>

      <div class="transport-field">
        <div class="field-title">
          <span>交通方式</span>
          <small>{{ criteria.transportModes?.length ? "依已選方式比較" : "未選時自動比較最短時間" }}</small>
        </div>
        <div class="transport-grid">
          <button
            v-for="mode in TRANSPORT_MODES"
            :key="mode.id"
            class="transport-chip"
            :class="{ selected: criteria.transportModes?.includes(mode.id) }"
            type="button"
            @click="toggleTransport(mode.id)"
          >
            <TransportIcon :name="mode.icon" />
            <span>{{ mode.label }}</span>
          </button>
        </div>
      </div>

      <div class="location-field">
        <div>
          <span>出發定位</span>
          <strong>{{ locationText }}</strong>
          <small>{{ locationSubtext }}</small>
        </div>
        <button class="ghost-action compact" type="button" :disabled="locating" @click="emit('locate')">
          {{ locating ? "Locating..." : "Use location" }}
        </button>
      </div>

      <div class="favorite-start-switcher" v-if="favoriteStarts.length || canUseFallback">
        <button
          v-if="canUseFallback"
          class="start-chip"
          type="button"
          @click="useFallbackLocation"
        >
          台北車站
        </button>
        <button
          v-for="start in favoriteStarts"
          :key="start.id"
          class="start-chip"
          :class="{ selected: criteria.locationSource === 'favorite' && criteria.location === `favorite:${start.id}` }"
          type="button"
          @click="emit('use-favorite-start', start)"
        >
          {{ start.label }}
        </button>
      </div>

      <div class="select-grid">
        <div class="dropdown-field">
          <span>天氣</span>
          <div class="calm-select" :class="{ open: openSelect === 'weather' }">
            <button class="calm-select-trigger" type="button" @click="openSelect = openSelect === 'weather' ? '' : 'weather'">
              <strong>{{ WEATHER_LABELS[criteria.weatherPreference] }}</strong>
            </button>
            <Transition name="select-pop">
              <div v-if="openSelect === 'weather'" class="calm-select-menu">
                <button
                  v-for="(label, value) in WEATHER_LABELS"
                  :key="value"
                  class="calm-select-option"
                  :class="{ selected: criteria.weatherPreference === value }"
                  type="button"
                  @click="chooseSelect({ weatherPreference: value })"
                >
                  <span>{{ label }}</span>
                  <i v-if="criteria.weatherPreference === value">✓</i>
                </button>
              </div>
            </Transition>
          </div>
        </div>
        <div class="dropdown-field">
          <span>預算</span>
          <div class="calm-select" :class="{ open: openSelect === 'budget' }">
            <button class="calm-select-trigger" type="button" @click="openSelect = openSelect === 'budget' ? '' : 'budget'">
              <strong>{{ BUDGET_LABELS[criteria.budget] }}</strong>
            </button>
            <Transition name="select-pop">
              <div v-if="openSelect === 'budget'" class="calm-select-menu">
                <button
                  v-for="(label, value) in BUDGET_LABELS"
                  :key="value"
                  class="calm-select-option"
                  :class="{ selected: criteria.budget === value }"
                  type="button"
                  @click="chooseSelect({ budget: value })"
                >
                  <span>{{ label }}</span>
                  <i v-if="criteria.budget === value">✓</i>
                </button>
              </div>
            </Transition>
          </div>
        </div>
      </div>

      <button class="primary-action" type="button" :disabled="loading || locating" @click="emit('find')">
        {{ loading ? "Finding..." : locating ? "Locating..." : "Find my next stop" }}
      </button>
    </section>
  </main>
</template>
