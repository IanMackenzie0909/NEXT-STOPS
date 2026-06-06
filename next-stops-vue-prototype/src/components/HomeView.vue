<script setup>
import { computed, ref } from "vue";
import AppIcon from "./AppIcon.vue";
import IconGlyph from "./IconGlyph.vue";
import { BUDGET_LABELS, LOCATION_FALLBACK_LABEL, MOODS, WEATHER_LABELS } from "../constants";
import { formatTime } from "../utils/formatters";

const props = defineProps({
  criteria: { type: Object, required: true },
  loading: { type: Boolean, default: false },
  locating: { type: Boolean, default: false },
  savedCount: { type: Number, default: 0 },
  ambientEnabled: { type: Boolean, default: false },
});
const emit = defineEmits(["update:criteria", "find", "locate", "navigate", "toggle-ambient"]);
const openSelect = ref("");

const locationText = computed(() => {
  if (props.criteria.locationSource === "gps" && props.criteria.lat && props.criteria.lon) {
    return "目前定位 • 你的定位";
  }
  return props.criteria.locationLabel || LOCATION_FALLBACK_LABEL;
});

const locationSubtext = computed(() => {
  if (props.criteria.locationSource === "gps" && props.criteria.lat && props.criteria.lon) {
    return `(${Number(props.criteria.lat).toFixed(4)}, ${Number(props.criteria.lon).toFixed(4)})`;
  }
  return "目前使用預設起點；按 Use location 可改用即時定位。";
});

function patch(updates) {
  emit("update:criteria", updates);
}

function chooseSelect(updates) {
  patch(updates);
  openSelect.value = "";
}
</script>

<template>
  <main class="screen home-screen">
    <header class="home-header">
      <div>
        <p class="muted">Good morning</p>
        <h1>Where to next?</h1>
      </div>
      <button class="icon-button sound-button" :class="{ active: ambientEnabled }" type="button" title="Ambient sound" @click="emit('toggle-ambient')">
        <IconGlyph name="sound" />
      </button>
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
