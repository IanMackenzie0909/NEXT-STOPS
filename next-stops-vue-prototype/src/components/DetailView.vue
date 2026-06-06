<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { getContext, getPlace } from "../api/nextStopsApi";
import { LOCATION_LABELS } from "../constants";
import { budgetLabel, formatWeatherNow } from "../utils/formatters";

const props = defineProps({
  placeId: { type: String, required: true },
  fallbackPlace: { type: Object, default: null },
  criteria: { type: Object, required: true },
  saved: { type: Boolean, default: false },
});
const emit = defineEmits(["navigate", "toggle-save", "toast"]);

const place = ref(props.fallbackPlace);
const context = ref(null);
const loading = ref(true);
const travelTime = computed(() => place.value?.matched_travel_time ?? place.value?.travel_time_minutes ?? 0);

async function loadPlace() {
  loading.value = true;
  try {
    place.value = await getPlace(props.placeId);
    if (place.value?.lat && place.value?.lng) context.value = await getContext(place.value.lat, place.value.lng).catch(() => null);
  } catch (error) {
    emit("toast", error.message);
    if (!place.value) emit("navigate", "/results");
  } finally {
    loading.value = false;
  }
}

onMounted(loadPlace);
watch(() => props.placeId, () => {
  place.value = props.fallbackPlace;
  context.value = null;
  loadPlace();
});
</script>

<template>
  <main class="screen detail-screen">
    <div v-if="loading && !place" class="empty-state">
      <h2>Loading...</h2>
    </div>

    <template v-else-if="place">
      <header class="screen-header">
        <button class="back-button" type="button" @click="emit('navigate', '/results')">‹</button>
        <div>
          <p class="muted">MATCH SCORE {{ place.score }}%</p>
          <h1>{{ place.name }}</h1>
        </div>
      </header>

      <section class="detail-map-card">
        <div class="soft-map large" aria-hidden="true">
          <div class="route-line"></div>
          <div class="pin one"></div>
          <div class="pin two"></div>
          <span>{{ place.category }}</span>
        </div>
      </section>

      <section class="detail-copy">
        <p>{{ place.description }}</p>
        <div class="metric-row wrap">
          <span>{{ travelTime }} min</span>
          <span>{{ budgetLabel(place.budget) }}</span>
          <span>{{ formatWeatherNow(context) }}</span>
        </div>
      </section>

      <section class="reason-list">
        <div><strong>Why now</strong><span>{{ place.reason }}</span></div>
        <div><strong>Route</strong><span>{{ place.route_hint }}</span></div>
        <div><strong>Start</strong><span>{{ LOCATION_LABELS[criteria.location] }}</span></div>
      </section>

      <div class="action-row">
        <button class="primary-action" type="button" @click="emit('toggle-save', place)">
          {{ saved ? "Saved today" : "Add to today" }}
        </button>
        <a class="ghost-action" target="_blank" rel="noreferrer" :href="`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${place.name} ${place.address}`)}`">Map</a>
      </div>
    </template>
  </main>
</template>
