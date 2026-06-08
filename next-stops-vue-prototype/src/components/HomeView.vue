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
  canSavePreferences: { type: Boolean, default: false },
  savingPreferences: { type: Boolean, default: false },
  canSaveLocation: { type: Boolean, default: false },
  savingLocation: { type: Boolean, default: false },
  departureLocations: { type: Array, default: () => [] },
});

const emit = defineEmits(["update:criteria", "find", "locate", "navigate", "save-preferences", "save-location"]);
const openSelect = ref("");

const usableDepartureLocations = computed(() => props.departureLocations.filter((location) => (
  location
  && Number.isFinite(Number(location.lat))
  && Number.isFinite(Number(location.lon))
)));

const locationText = computed(() => {
  if (props.criteria.locationSource === "gps" && props.criteria.lat && props.criteria.lon) {
    return "Current location";
  }
  return props.criteria.locationLabel || LOCATION_FALLBACK_LABEL;
});

const locationSubtext = computed(() => {
  if (props.criteria.lat && props.criteria.lon) {
    return `(${Number(props.criteria.lat).toFixed(4)}, ${Number(props.criteria.lon).toFixed(4)})`;
  }
  return "Use location or choose a saved departure point.";
});

const savedDepartureLabel = computed(() => {
  const selected = usableDepartureLocations.value.find((location) => (
    props.criteria.locationSource === "saved" && props.criteria.location === location.id
  ));
  return selected?.label || "Choose saved start";
});

function patch(updates) {
  emit("update:criteria", updates);
}

function chooseSelect(updates) {
  patch(updates);
  openSelect.value = "";
}

function chooseDepartureLocation(location) {
  const lat = Number(location.lat);
  const lon = Number(location.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
  chooseSelect({
    location: location.id,
    locationLabel: location.label,
    locationSource: "saved",
    lat,
    lon,
  });
}

function toggleTransport(modeId) {
  const current = Array.isArray(props.criteria.transportModes) ? props.criteria.transportModes : [];
  patch({
    transportModes: current.includes(modeId)
      ? current.filter((item) => item !== modeId)
      : [...current, modeId],
  });
}
</script>

<template>
  <main class="screen home-screen">
    <header class="home-header">
      <div>
        <p class="muted">Good morning</p>
        <h1>Where to next?</h1>
      </div>
    </header>

    <section class="choice-panel">
      <div class="panel-head">
        <AppIcon />
        <div>
          <h2>Find a calm stop nearby</h2>
          <p>Set the mood, time, transport, and departure point for the next recommendation.</p>
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
        <span>Available time <strong>{{ formatTime(criteria.time) }}</strong></span>
        <input type="range" min="30" max="300" step="15" :value="criteria.time" @input="patch({ time: Number($event.target.value) })" />
      </label>

      <label class="range-field">
        <span>Move time limit <strong>{{ criteria.distance }} min</strong></span>
        <input type="range" min="10" max="90" step="5" :value="criteria.distance" @input="patch({ distance: Number($event.target.value) })" />
      </label>

      <div class="transport-field">
        <div class="field-title">
          <span>Transport</span>
          <small>{{ criteria.transportModes?.length ? "Selected modes" : "Any available mode" }}</small>
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
        <div class="location-copy">
          <span>Departure point</span>
          <strong>{{ locationText }}</strong>
          <small>{{ locationSubtext }}</small>
        </div>
        <div class="location-controls">
          <div v-if="usableDepartureLocations.length" class="saved-location-select">
            <span>Saved start</span>
            <div class="calm-select" :class="{ open: openSelect === 'departure' }">
              <button class="calm-select-trigger" type="button" @click="openSelect = openSelect === 'departure' ? '' : 'departure'">
                <strong>{{ savedDepartureLabel }}</strong>
              </button>
              <Transition name="select-pop">
                <div v-if="openSelect === 'departure'" class="calm-select-menu">
                  <button
                    v-for="location in usableDepartureLocations"
                    :key="location.id"
                    class="calm-select-option saved-location-option"
                    :class="{ selected: criteria.locationSource === 'saved' && criteria.location === location.id }"
                    type="button"
                    @click="chooseDepartureLocation(location)"
                  >
                    <span>{{ location.label }}</span>
                    <i v-if="location.is_default">Default</i>
                  </button>
                </div>
              </Transition>
            </div>
          </div>
          <div class="location-actions">
            <button class="ghost-action compact" type="button" :disabled="locating" @click="emit('locate')">
              {{ locating ? "Locating..." : "Use location" }}
            </button>
            <button
              v-if="canSaveLocation"
              class="ghost-action compact"
              type="button"
              :disabled="savingLocation || locating"
              @click="emit('save-location')"
            >
              {{ savingLocation ? "Saving..." : "Save location" }}
            </button>
          </div>
        </div>
      </div>

      <div class="select-grid">
        <div class="dropdown-field">
          <span>Weather</span>
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
                  <i v-if="criteria.weatherPreference === value">OK</i>
                </button>
              </div>
            </Transition>
          </div>
        </div>
        <div class="dropdown-field">
          <span>Budget</span>
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
                  <i v-if="criteria.budget === value">OK</i>
                </button>
              </div>
            </Transition>
          </div>
        </div>
      </div>

      <button class="primary-action" type="button" :disabled="loading || locating" @click="emit('find')">
        {{ loading ? "Finding..." : locating ? "Locating..." : "Find my next stop" }}
      </button>
      <button
        v-if="canSavePreferences"
        class="ghost-action save-preferences-action"
        type="button"
        :disabled="savingPreferences"
        @click="emit('save-preferences')"
      >
        {{ savingPreferences ? "Saving..." : "Save preferences" }}
      </button>
    </section>
  </main>
</template>
