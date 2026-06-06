<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import BottomNav from "./components/BottomNav.vue";
import DetailView from "./components/DetailView.vue";
import HomeView from "./components/HomeView.vue";
import ResultsView from "./components/ResultsView.vue";
import SavedView from "./components/SavedView.vue";
import Toast from "./components/Toast.vue";
import { deleteSavedPlace, getRecommendations, getSavedPlaces, savePlace, updateSavedPlace } from "./api/nextStopsApi";

const criteria = reactive({
  mood: "relaxing_walk",
  time: 120,
  distance: 30,
  location: "taipei_main",
  weatherPreference: "any",
  budget: "medium",
});

const route = ref(window.location.hash.replace(/^#/, "") || "/");
const results = ref([]);
const saved = ref([]);
const loading = ref(false);
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

async function findStops() {
  if (!criteria.mood) return;
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
  <div class="prototype-shell">
    <div class="phone">
      <div class="phone-screen">
        <HomeView
          v-if="routeName === 'home'"
          :criteria="criteria"
          :loading="loading"
          :saved-count="saved.length"
          @update:criteria="updateCriteria"
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
  </div>
</template>
