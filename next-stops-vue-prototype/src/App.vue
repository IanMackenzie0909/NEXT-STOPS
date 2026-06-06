<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import BottomNav from "./components/BottomNav.vue";
import DetailView from "./components/DetailView.vue";
import HomeView from "./components/HomeView.vue";
import ResultsView from "./components/ResultsView.vue";
import SavedView from "./components/SavedView.vue";
import Toast from "./components/Toast.vue";
import { deleteSavedPlace, getRecommendations, getSavedPlaces, savePlace, updateSavedPlace } from "./api/nextStopsApi";
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
const toastMessage = ref("");
let toastTimer;

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
  if (!criteria.mood) return;
  if (criteria.locationSource !== "gps") await locateUser();
  loading.value = true;
  try {
    const data = await getRecommendations({ ...criteria });
    results.value = data.results || [];
    navigate("/results");
  } catch (error) {
    showToast(`推薦資料無法取得：${error.message}`);
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
    id: place.id,
    name: place.name,
    category: place.category,
    address: place.address,
    lat: place.lat,
    lng: place.lng,
    score: place.score,
    note: "",
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
      <HomeView
        v-if="routeName === 'home'"
        :criteria="criteria"
        :loading="loading"
        :locating="locating"
        :saved-count="saved.length"
        @update:criteria="updateCriteria"
        @locate="locateUser"
        @find="findStops"
        @navigate="navigate"
      />
      <ResultsView
        v-else-if="routeName === 'results'"
        :criteria="criteria"
        :results="results"
        :saved-ids="savedIds"
        @navigate="navigate"
        @view="(id) => navigate(`/place/${id}`)"
        @toggle-save="toggleSave"
      />
      <DetailView
        v-else-if="routeName === 'detail'"
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
        :saved="saved"
        @navigate="navigate"
        @remove="removeSaved"
        @update-note="updateNote"
      />
      <BottomNav :route="route" :saved-count="saved.length" @navigate="navigate" />
      <Toast :message="toastMessage" />
    </div>
  </div>
</template>
