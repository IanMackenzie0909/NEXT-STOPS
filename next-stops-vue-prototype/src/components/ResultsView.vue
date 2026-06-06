<script setup>
import { LOCATION_LABELS, MOODS } from "../constants";

defineProps({
  criteria: { type: Object, required: true },
  results: { type: Array, required: true },
  savedIds: { type: Array, required: true },
});
const emit = defineEmits(["navigate", "view", "toggle-save"]);
</script>

<template>
  <main class="screen results-screen">
    <header class="screen-header">
      <button class="back-button" type="button" @click="emit('navigate', '/')">‹</button>
      <div>
        <p class="muted">{{ LOCATION_LABELS[criteria.location] }} 出發</p>
        <h1>{{ MOODS.find((item) => item.id === criteria.mood)?.label || "推薦" }}</h1>
      </div>
    </header>

    <section v-if="results.length" class="result-list">
      <article v-for="(place, index) in results" :key="place.id" class="place-card">
        <button class="place-main" type="button" @click="emit('view', place.id)">
          <span class="rank">0{{ index + 1 }}</span>
          <div>
            <h2>{{ place.name }}</h2>
            <p>{{ place.category }} / {{ place.address }}</p>
          </div>
        </button>
        <div class="badge-row">
          <span>{{ place.matched_travel_time ?? place.travel_time_minutes }} min</span>
          <span>{{ place.weather_summary }}</span>
          <span>{{ place.budget }}</span>
        </div>
        <p class="reason">{{ place.reason }}</p>
        <div class="card-footer">
          <div class="score-pill">{{ place.score }}%</div>
          <button class="ghost-action" :class="{ saved: savedIds.includes(place.id) }" type="button" @click="emit('toggle-save', place)">
            {{ savedIds.includes(place.id) ? "Saved" : "Save" }}
          </button>
        </div>
      </article>
    </section>

    <section v-else class="empty-state">
      <h2>No results yet</h2>
      <p>先回首頁設定心情，再產生下一站推薦。</p>
      <button class="primary-action" type="button" @click="emit('navigate', '/')">Back home</button>
    </section>
  </main>
</template>
