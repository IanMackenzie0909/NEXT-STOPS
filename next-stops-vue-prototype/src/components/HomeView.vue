<script setup>
import AppIcon from "./AppIcon.vue";
import { BUDGET_LABELS, LOCATION_LABELS, MOODS, WEATHER_LABELS } from "../constants";
import { formatTime } from "../utils/formatters";

defineProps({
  criteria: { type: Object, required: true },
  loading: { type: Boolean, default: false },
  savedCount: { type: Number, default: 0 },
});
const emit = defineEmits(["update:criteria", "find", "navigate"]);

function patch(updates) {
  emit("update:criteria", updates);
}
</script>

<template>
  <main class="screen home-screen">
    <header class="home-header">
      <div>
        <p class="muted">Good morning</p>
        <h1>Where to next?</h1>
      </div>
      <button class="icon-button" type="button" title="Today plan" @click="emit('navigate', '/saved')">
        ✓<i v-if="savedCount">{{ savedCount }}</i>
      </button>
    </header>

    <section class="next-card">
      <div class="card-kicker">
        <span>YOUR NEXT STOP</span>
        <strong>{{ criteria.mood ? MOODS.find((item) => item.id === criteria.mood)?.short : "Set" }}</strong>
      </div>
      <div class="soft-map" aria-hidden="true">
        <div class="route-line"></div>
        <div class="pin one"></div>
        <div class="pin two"></div>
      </div>
      <h2>Find a calm stop nearby</h2>
      <p>依照心情、時間、天氣偏好與出發區域，挑一個現在能去的臺北地點。</p>
      <div class="metric-row">
        <span>{{ formatTime(criteria.time) }}</span>
        <span>{{ LOCATION_LABELS[criteria.location] }}</span>
        <span>{{ WEATHER_LABELS[criteria.weatherPreference] }}</span>
      </div>
    </section>

    <section class="choice-panel">
      <div class="panel-head">
        <AppIcon />
        <div>
          <h2>Set today</h2>
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

      <div class="select-grid">
        <label>
          <span>出發</span>
          <select :value="criteria.location" @change="patch({ location: $event.target.value })">
            <option v-for="(label, value) in LOCATION_LABELS" :key="value" :value="value">{{ label }}</option>
          </select>
        </label>
        <label>
          <span>天氣</span>
          <select :value="criteria.weatherPreference" @change="patch({ weatherPreference: $event.target.value })">
            <option v-for="(label, value) in WEATHER_LABELS" :key="value" :value="value">{{ label }}</option>
          </select>
        </label>
        <label>
          <span>預算</span>
          <select :value="criteria.budget" @change="patch({ budget: $event.target.value })">
            <option v-for="(label, value) in BUDGET_LABELS" :key="value" :value="value">{{ label }}</option>
          </select>
        </label>
      </div>

      <button class="primary-action" type="button" :disabled="loading" @click="emit('find')">
        {{ loading ? "Finding..." : "Find my next stop" }}
      </button>
    </section>
  </main>
</template>
