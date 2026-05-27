<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import TopBar from "./components/TopBar.vue";
import HomeView from "./components/HomeView.vue";
import ResultsView from "./components/ResultsView.vue";
import DetailView from "./components/DetailView.vue";
import SavedView from "./components/SavedView.vue";
import Toast from "./components/Toast.vue";
import {
  deleteSavedPlace,
  getRecommendations,
  getSavedPlaces,
  savePlace,
  updateSavedPlace,
} from "./api/nextStopsApi";

const criteria = reactive({
  mood: null,
  time: 120,
  distance: 30,
  location: "taipei_main",
  weatherPreference: "any",
  budget: "medium",
});

const route = ref(window.location.hash.replace(/^#/, "") || "/");
const results = ref([]);
const saved = ref(loadLocalSaved());
const loading = ref(false);
const toastMessage = ref("");
let toastTimer;

const routeName = computed(() => {
  if (route.value.startsWith("/place/")) return "detail";
  if (route.value === "/results") return "results";
  if (route.value === "/saved") return "saved";
  return "home";
});

const activePlaceId = computed(() => {
  return route.value.startsWith("/place/") ? decodeURIComponent(route.value.replace("/place/", "")) : "";
});

const savedIds = computed(() => saved.value.map((item) => item.id));

function updateCriteria(updates) {
  Object.assign(criteria, updates);
}

function navigate(path) {
  const target = path || "/";
  if (window.location.hash.replace(/^#/, "") === target) {
    route.value = target;
    return;
  }
  window.location.hash = target;
}

function onHashChange() {
  route.value = window.location.hash.replace(/^#/, "") || "/";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function findStops() {
  if (!criteria.mood) return;
  loading.value = true;
  try {
    const data = await getRecommendations({ ...criteria });
    results.value = data.results || [];
    navigate("/results");
  } catch (error) {
    showToast(`推薦 API 無法使用：${error.message}`);
  } finally {
    loading.value = false;
  }
}

async function syncSaved() {
  try {
    saved.value = await getSavedPlaces();
    persistLocalSaved();
  } catch (error) {
    showToast(`收藏 API 無法使用：${error.message}`);
  }
}

async function toggleSave(place) {
  if (!place?.id) return;
  if (isSaved(place.id)) {
    saved.value = saved.value.filter((item) => item.id !== place.id);
    persistLocalSaved();
    try {
      await deleteSavedPlace(place.id);
    } catch (error) {
      showToast(`刪除收藏暫時只保留在本機：${error.message}`);
    }
    showToast("已從收藏移除");
    return;
  }

  const item = {
    id: place.id,
    name: place.name,
    category: place.category,
    address: place.address,
    lat: place.lat,
    lng: place.lng,
    note: "",
    created_at: new Date().toISOString(),
  };
  saved.value = [item, ...saved.value.filter((entry) => entry.id !== item.id)];
  persistLocalSaved();
  try {
    const savedItem = await savePlace(item);
    saved.value = [savedItem, ...saved.value.filter((entry) => entry.id !== savedItem.id)];
    persistLocalSaved();
  } catch (error) {
    showToast(`新增收藏暫時只保留在本機：${error.message}`);
  }
  showToast("已收藏");
}

async function removeSaved(id) {
  saved.value = saved.value.filter((item) => item.id !== id);
  persistLocalSaved();
  try {
    await deleteSavedPlace(id);
  } catch (error) {
    showToast(`移除收藏暫時只保留在本機：${error.message}`);
  }
}

async function updateNote(id, note) {
  saved.value = saved.value.map((item) => (item.id === id ? { ...item, note } : item));
  persistLocalSaved();
  try {
    await updateSavedPlace(id, { note });
  } catch (error) {
    console.warn("收藏備註暫時只保留在本機：", error.message);
  }
}

function isSaved(id) {
  return savedIds.value.includes(id);
}

function fallbackPlace(id) {
  return results.value.find((place) => place.id === id) || saved.value.find((place) => place.id === id) || null;
}

function loadLocalSaved() {
  try {
    return JSON.parse(localStorage.getItem("nextstops:saved") || "[]");
  } catch {
    return [];
  }
}

function persistLocalSaved() {
  localStorage.setItem("nextstops:saved", JSON.stringify(saved.value));
}

function showToast(message) {
  toastMessage.value = message;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toastMessage.value = "";
  }, 2200);
}

onMounted(() => {
  window.addEventListener("hashchange", onHashChange);
  syncSaved();
  onHashChange();
});
</script>

<template>
  <TopBar :route="route" :saved-count="saved.length" @navigate="navigate" />

  <main>
    <HomeView
      v-if="routeName === 'home'"
      :criteria="criteria"
      :loading="loading"
      @update:criteria="updateCriteria"
      @find="findStops"
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
      :saved="isSaved(activePlaceId)"
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
      @toast="showToast"
    />
  </main>

  <footer class="footer">
    <span>NEXT STOPS Vue 預覽版 / 已串接真實後端 API</span>
  </footer>

  <Toast :message="toastMessage" />
</template>
