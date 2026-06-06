<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import BottomNav from "./components/BottomNav.vue";
import DetailView from "./components/DetailView.vue";
import HomeView from "./components/HomeView.vue";
import ResultsView from "./components/ResultsView.vue";
import SavedView from "./components/SavedView.vue";
import Toast from "./components/Toast.vue";
import IconGlyph from "./components/IconGlyph.vue";
import { deleteSavedPlace, getRecommendations, getSavedPlaces, savePlace, submitRecommendationFeedback, updateSavedPlace } from "./api/nextStopsApi";
import { LOCATION_FALLBACK_LABEL } from "./constants";

const criteria = reactive({
  mood: "relaxing_walk",
  time: 120,
  distance: 30,
  location: "taipei_main",
  locationLabel: LOCATION_FALLBACK_LABEL,
  locationSource: "fallback",
  lat: null,
  lon: null,
  weatherPreference: "any",
  budget: "medium",
});

const route = ref(window.location.hash.replace(/^#/, "") || "/");
const results = ref([]);
const saved = ref([]);
const loading = ref(false);
const locating = ref(false);
const recommendationError = ref("");
const latestRequestId = ref("");
const feedbackByPlace = ref({});
const toastMessage = ref("");
const ambientEnabled = ref(false);
let toastTimer;
let audioContext;
let ambientGain;
let ambientNodes = [];

const routeName = computed(() => {
  if (route.value.startsWith("/place/")) return "detail";
  if (route.value === "/results") return "results";
  if (route.value === "/saved") return "saved";
  return "home";
});
const activePlaceId = computed(() => route.value.startsWith("/place/") ? decodeURIComponent(route.value.replace("/place/", "")) : "");
const savedIds = computed(() => saved.value.map((item) => item.id));

function navigate(path) {
  const target = path || "/";
  if (window.location.hash.replace(/^#/, "") === target) route.value = target;
  else window.location.hash = target;
}

function handleNavigate(path) {
  if (path === "/results" && !results.value.length && !loading.value) {
    findStops();
    return;
  }
  navigate(path);
}

function updateCriteria(updates) {
  Object.assign(criteria, updates);
}

function locateUser() {
  if (!("geolocation" in navigator)) {
    showToast("瀏覽器不支援定位，先使用台北車站作為起點");
    updateCriteria({
      location: "taipei_main",
      locationLabel: LOCATION_FALLBACK_LABEL,
      locationSource: "fallback",
      lat: null,
      lon: null,
    });
    return Promise.resolve(false);
  }

  locating.value = true;
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const lat = Number(position.coords.latitude.toFixed(6));
        const lon = Number(position.coords.longitude.toFixed(6));
        updateCriteria({
          location: "current",
          locationLabel: "目前定位",
          locationSource: "gps",
          lat,
          lon,
        });
        locating.value = false;
        showToast("已更新目前定位");
        resolve(true);
      },
      (error) => {
        locating.value = false;
        showToast(error.code === 1 ? "定位權限未開啟，先使用台北車站作為起點" : "定位失敗，先使用台北車站作為起點");
        updateCriteria({
          location: "taipei_main",
          locationLabel: LOCATION_FALLBACK_LABEL,
          locationSource: "fallback",
          lat: null,
          lon: null,
        });
        resolve(false);
      },
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 120000 },
    );
  });
}

async function findStops() {
  if (loading.value) return;
  if (!criteria.mood) return;
  loading.value = true;
  recommendationError.value = "";
  results.value = [];
  navigate("/results");
  try {
    if (criteria.locationSource !== "gps") await locateUser();
    const data = await getRecommendations({ ...criteria });
    latestRequestId.value = data.request_id || "";
    results.value = data.results || [];
    if (!results.value.length) {
      recommendationError.value = data.request_id
        ? `後端已完成推薦請求 ${data.request_id}，但沒有回傳任何地點。請檢查景點資料 cache 或推薦篩選條件。`
        : "後端已回應，但沒有回傳任何推薦地點。請檢查景點資料 cache 或推薦篩選條件。";
    }
  } catch (error) {
    recommendationError.value = error.message || "推薦資料無法取得";
    console.error("NEXT STOPS recommendation failed:", error);
    showToast(`推薦資料無法取得：${recommendationError.value}`);
  } finally {
    loading.value = false;
  }
}

async function syncSaved() {
  saved.value = await getSavedPlaces();
}

async function toggleSave(place) {
  if (!place?.id) return;
  if (savedIds.value.includes(place.id)) {
    saved.value = saved.value.filter((item) => item.id !== place.id);
    await deleteSavedPlace(place.id);
    showToast("已從今天清單移除");
    return;
  }
  const item = {
    ...place,
    id: place.id,
    name: place.name,
    category: place.category,
    address: place.address,
    lat: place.lat,
    lng: place.lng,
    lon: place.lon ?? place.lng,
    score: place.score,
    note: place.note || "",
    created_at: new Date().toISOString(),
  };
  const savedItem = await savePlace(item);
  saved.value = [savedItem, ...saved.value.filter((entry) => entry.id !== savedItem.id)];
  showToast("已加入今天清單");
}

async function removeSaved(id) {
  saved.value = saved.value.filter((item) => item.id !== id);
  await deleteSavedPlace(id);
}

async function updateNote(id, note) {
  saved.value = saved.value.map((item) => item.id === id ? { ...item, note } : item);
  await updateSavedPlace(id, { note });
}

async function submitFeedback(placeId, feedbackType) {
  feedbackByPlace.value = { ...feedbackByPlace.value, [placeId]: feedbackType };
  try {
    await submitRecommendationFeedback(placeId, feedbackType, latestRequestId.value);
    showToast("已記錄你的偏好");
  } catch (error) {
    showToast(`偏好暫時無法送出：${error.message}`);
  }
}

function fallbackPlace(id) {
  return results.value.find((place) => place.id === id) || saved.value.find((place) => place.id === id) || null;
}

function showToast(message) {
  toastMessage.value = message;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toastMessage.value = "";
  }, 2200);
}

async function toggleAmbient() {
  if (ambientEnabled.value) {
    stopAmbient();
    return;
  }
  try {
    startAmbient();
    ambientEnabled.value = true;
  } catch (error) {
    showToast(`音景無法啟用：${error.message}`);
  }
}

function startAmbient() {
  const AudioContext = globalThis.AudioContext || globalThis.webkitAudioContext;
  if (!AudioContext) throw new Error("瀏覽器不支援 Web Audio");
  audioContext = audioContext || new AudioContext();
  if (audioContext.state === "suspended") audioContext.resume();
  ambientGain = audioContext.createGain();
  ambientGain.gain.setValueAtTime(0.0001, audioContext.currentTime);
  ambientGain.gain.exponentialRampToValueAtTime(0.035, audioContext.currentTime + 1.6);
  ambientGain.connect(audioContext.destination);
  ambientNodes = [196, 246.94, 329.63].map((frequency, index) => {
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();
    oscillator.type = index === 0 ? "sine" : "triangle";
    oscillator.frequency.value = frequency;
    gain.gain.value = index === 0 ? 0.48 : 0.18;
    oscillator.connect(gain);
    gain.connect(ambientGain);
    oscillator.start();
    return { oscillator, gain };
  });
}

function stopAmbient() {
  ambientEnabled.value = false;
  if (!audioContext || !ambientGain) return;
  const stopAt = audioContext.currentTime + 0.8;
  ambientGain.gain.cancelScheduledValues(audioContext.currentTime);
  ambientGain.gain.setValueAtTime(Math.max(ambientGain.gain.value, 0.0001), audioContext.currentTime);
  ambientGain.gain.exponentialRampToValueAtTime(0.0001, stopAt);
  setTimeout(() => {
    for (const node of ambientNodes) {
      try {
        node.oscillator.stop();
        node.oscillator.disconnect();
        node.gain.disconnect();
      } catch {
        // Oscillators can only be stopped once.
      }
    }
    ambientNodes = [];
    ambientGain?.disconnect();
    ambientGain = null;
  }, 900);
}

onMounted(() => {
  window.addEventListener("hashchange", () => {
    route.value = window.location.hash.replace(/^#/, "") || "/";
  });
  syncSaved();
});
</script>

<template>
  <div class="app-shell">
    <div class="app-surface">
      <Transition name="screen-fade" mode="out-in">
        <HomeView
          v-if="routeName === 'home'"
          key="home"
          :criteria="criteria"
          :loading="loading"
          :locating="locating"
          :saved-count="saved.length"
          :ambient-enabled="ambientEnabled"
          @update:criteria="updateCriteria"
          @locate="locateUser"
          @find="findStops"
          @navigate="handleNavigate"
          @toggle-ambient="toggleAmbient"
        />
        <ResultsView
          v-else-if="routeName === 'results'"
          key="results"
          :criteria="criteria"
          :results="results"
          :saved-ids="savedIds"
          :feedback-by-place="feedbackByPlace"
          :loading="loading || locating"
          :error="recommendationError"
          @navigate="handleNavigate"
          @find="findStops"
          @view="(id) => navigate(`/place/${id}`)"
          @toggle-save="toggleSave"
          @feedback="submitFeedback"
        />
        <DetailView
          v-else-if="routeName === 'detail'"
          :key="`detail-${activePlaceId}`"
          :place-id="activePlaceId"
          :fallback-place="fallbackPlace(activePlaceId)"
          :criteria="criteria"
          :saved="savedIds.includes(activePlaceId)"
          @navigate="navigate"
          @toggle-save="toggleSave"
          @toast="showToast"
        />
        <SavedView
          v-else-if="routeName === 'saved'"
          key="saved"
          :saved="saved"
          @navigate="navigate"
          @remove="removeSaved"
          @update-note="updateNote"
        />
      </Transition>
    </div>
    <button
      v-if="routeName !== 'home'"
      class="ambient-toggle"
      :class="{ active: ambientEnabled }"
      type="button"
      title="Ambient sound"
      @click="toggleAmbient"
    >
      <IconGlyph name="sound" />
      <span>{{ ambientEnabled ? "Sound on" : "Sound" }}</span>
    </button>
    <BottomNav :route="route" :saved-count="saved.length" @navigate="handleNavigate" />
    <Toast :message="toastMessage" />
  </div>
</template>
